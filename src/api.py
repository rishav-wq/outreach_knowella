"""FastAPI backend — wraps the pipeline so the React UI can drive it over HTTP.

Run:  uvicorn src.api:app --reload --port 8000
The engine logic lives in pipeline/; this just exposes it as JSON endpoints.
"""
from __future__ import annotations

import glob
import os
import re
import tempfile
import threading

import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import auth, config, pipeline
from .engine import personalize
from .integrations import apollo, apollo_send, csv_source, email_verify, enrich
from .store import open_store

config.load_env()  # so Clerk/CORS env is available at app-construction time

# Every route requires a valid Clerk session token — unless Clerk is unconfigured
# (local dev), in which case require_auth is a no-op. See src/auth.py.
app = FastAPI(title="outreach-agent", dependencies=[Depends(auth.require_auth)])

# Localhost dev origins are always allowed; add the deployed frontend via the
# ALLOWED_ORIGINS env var (comma-separated), e.g. "https://outreach-web.onrender.com".
_origins = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:4173", "http://127.0.0.1:4173",
]
_origins += [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_DIR = "config"
_runs: dict = {}  # campaign -> {running, error, summary}


def _campaign_path(name: str) -> str:
    path = os.path.join(CONFIG_DIR, f"{name}.yaml")
    if not os.path.exists(path):
        raise HTTPException(404, f"campaign '{name}' not found")
    return path


def _load(name: str) -> dict:
    config.load_env()
    return config.load_campaign(_campaign_path(name))


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/campaigns")
def campaigns():
    # *.example.yaml is a documented template, not a runnable campaign — hide it.
    files = glob.glob(os.path.join(CONFIG_DIR, "*.yaml"))
    names = [os.path.splitext(os.path.basename(f))[0] for f in sorted(files)]
    return [n for n in names if not n.endswith(".example")]


class CampaignCreate(BaseModel):
    name: str
    icp: dict = {}
    offer: dict = {}
    knowledge: list = []
    voice: dict = {}
    research: dict = {}
    verify: dict = {}
    sending: dict = {}


@app.post("/api/campaigns")
def create_campaign(c: CampaignCreate):
    """Create a campaign config from the wizard. The slug is both filename and store key."""
    slug = re.sub(r"[^a-z0-9]+", "-", c.name.lower()).strip("-")
    if not slug:
        raise HTTPException(400, "campaign name must contain letters or numbers")
    path = os.path.join(CONFIG_DIR, f"{slug}.yaml")
    if os.path.exists(path):
        raise HTTPException(409, f"campaign '{slug}' already exists")
    cfg = {
        "name": slug,
        "icp": c.icp,
        "offer": c.offer,
        "knowledge": c.knowledge,
        "voice": c.voice,
        "research": c.research,
        "verify": c.verify,
        "sending": c.sending,
    }
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
    return {"created": slug}


@app.get("/api/campaign/config")
def campaign_config(campaign: str):
    """The raw campaign config (for settings display)."""
    return _load(campaign)


@app.get("/api/mailboxes")
def mailboxes(campaign: str | None = None):
    """The Apollo mailboxes you can send from, plus which one this campaign uses."""
    current = None
    if campaign:
        current = (_load(campaign).get("sending") or {}).get("mailbox_id")
    return {"mailboxes": apollo_send.list_mailboxes(), "current": current}


class MailboxSet(BaseModel):
    campaign: str
    mailbox_id: str


def _set_config_mailbox(name: str, mailbox_id: str, email: str) -> None:
    """Write sending.mailbox_id into the campaign YAML, preserving the file's
    layout and comments; the inline comment is refreshed to the new address."""
    path = _campaign_path(name)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    comment = f"     # {email}" if email else ""
    new, n = re.subn(r"(?m)^(\s*)mailbox_id:.*$",
                     lambda m: f"{m.group(1)}mailbox_id: {mailbox_id}{comment}", text)
    if n == 0:  # no existing key — fall back to a structured write under sending
        cfg = yaml.safe_load(text) or {}
        cfg.setdefault("sending", {})["mailbox_id"] = mailbox_id
        new = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)


@app.post("/api/campaign/mailbox")
def set_campaign_mailbox(m: MailboxSet):
    """Choose which Apollo mailbox this campaign sends from."""
    _campaign_path(m.campaign)  # 404s if the campaign doesn't exist
    match = next((b for b in apollo_send.list_mailboxes() if b["id"] == m.mailbox_id), None)
    if not match:
        raise HTTPException(400, "that mailbox is not one of your Apollo email accounts")
    _set_config_mailbox(m.campaign, m.mailbox_id, match["email"])
    return {"mailbox_id": m.mailbox_id, "email": match["email"]}


@app.get("/api/status")
def status(campaign: str):
    cfg = _load(campaign)
    store = open_store()
    send_cfg = cfg.get("sending") or {}
    # Sending goes through Apollo sequences: needs the key + a sequence + a mailbox.
    sendable = (bool(os.environ.get("APOLLO_API_KEY"))
                and bool(send_cfg.get("sequence_id")) and bool(send_cfg.get("mailbox_id")))
    return {
        "counts": store.counts(cfg["name"]),
        "tokens": store.token_totals(cfg["name"]),
        "sendable": sendable,
        "mailbox_id": send_cfg.get("mailbox_id") or "",
        "guardrails": {
            "daily_cap": int(send_cfg.get("daily_cap") or 0),
            "sent_today": store.sent_today(cfg["name"]),
            "window": send_cfg.get("window") or {},
        },
    }


@app.get("/api/leads")
def leads(campaign: str):
    cfg = _load(campaign)
    return open_store().lead_summaries(cfg["name"])


@app.get("/api/board")
def board(campaign: str):
    """All leads as kanban cards (status + source + review decision)."""
    cfg = _load(campaign)
    store = open_store()
    cards = store.lead_summaries(cfg["name"])
    for c in cards:
        c["decision"] = store.get_review(c["key"]) or ""
    return cards


@app.get("/api/lead")
def lead_detail(campaign: str, key: str):
    """Full detail for the slideout: email, facts, sending info, decision."""
    cfg = _load(campaign)
    store = open_store()
    lead = store.get_lead(key)
    if not lead:
        raise HTTPException(404, "lead not found")
    ob = store.get_outbox(key) or {}
    res = store.get_research_any(key)
    facts = [{"claim": f.claim, "source_url": f.source_url, "source_type": f.source_type}
             for f in (res.facts if res else [])]
    return {
        "key": key, "name": lead.full_name, "company": lead.company, "title": lead.title,
        "email": lead.email, "source": lead.source,
        "subject": ob.get("subject", ""), "body": ob.get("body", ""), "verdict": ob.get("verdict", ""),
        "facts": facts, "decision": store.get_review(key) or "", "edited": bool(ob.get("edited")),
        "verify": (store.get_verify(lead.email) or "") if lead.email else "",
        "verify_active": email_verify.has_key(),
        "require_deliverable": bool((cfg.get("verify") or {}).get("require_deliverable")),
    }


@app.get("/api/review")
def review(campaign: str):
    """Queued leads with their final email + the research facts behind it.

    Carries everything the focused review queue needs in one call: the draft,
    the quote-verified evidence, and the send-readiness signal per lead.
    """
    cfg = _load(campaign)
    store = open_store()
    verify_active = email_verify.has_key()
    require_deliverable = bool((cfg.get("verify") or {}).get("require_deliverable"))
    signature = personalize.signature_text(cfg)   # appended to every send; shown as a footer
    out = []
    for lead in store.leads(cfg["name"], "queued"):
        ob = store.get_outbox(lead.key)
        if not ob:
            continue
        res = store.get_research_any(lead.key)
        facts = [{"claim": f.claim, "quote": f.quote, "source_url": f.source_url,
                  "source_type": f.source_type, "published": f.published}
                 for f in (res.facts if res else [])]
        out.append({
            "key": lead.key, "name": lead.full_name, "company": lead.company,
            "title": lead.title, "source": lead.source,
            "verdict": ob["verdict"], "subject": ob["subject"], "body": ob["body"],
            "signature": signature,
            "facts": facts, "decision": store.get_review(lead.key) or "",
            "edited": bool(ob.get("edited")),
            "email": lead.email,
            "verify": (store.get_verify(lead.email) or "") if lead.email else "",
            "verify_active": verify_active, "require_deliverable": require_deliverable,
        })
    return out


def _apollo_target(cfg: dict) -> str:
    """The Apollo sequence id to read replies/stats from, or '' when unwired."""
    sid = (cfg.get("sending") or {}).get("sequence_id", "") or ""
    if not sid or sid.startswith("<") or not os.environ.get("APOLLO_API_KEY"):
        return ""
    return sid


def _lead_directory(store, campaign: str) -> dict:
    """email -> {name, company, key} for matching replies back to leads."""
    out = {}
    for s in store.lead_summaries(campaign):
        if s.get("email"):
            out[s["email"].lower()] = {"name": s["name"], "company": s["company"], "key": s["key"]}
    return out


def _msg_text(m: dict) -> str:
    b = m.get("body") or m.get("body_text") or m.get("body_html") or ""
    if isinstance(b, dict):
        b = b.get("text") or b.get("html") or ""
    return (b or "").strip()


@app.get("/api/inbox")
def inbox(campaign: str):
    """Latest reply per thread from the Apollo sequence. connected=false when unwired.

    Reply message shape is mapped defensively — it populates once leads reply;
    field names get a final pass against real reply data.
    """
    cfg = _load(campaign)
    sid = _apollo_target(cfg)
    if not sid:
        return {"connected": False, "items": []}
    try:
        raw = apollo_send.list_replies(sid)
    except Exception as e:
        return {"connected": False, "items": [], "error": str(e)}
    directory = _lead_directory(open_store(), cfg["name"])
    items = []
    for m in raw:
        lead_email = (m.get("from_email") or m.get("from_address") or "").lower()
        who = directory.get(lead_email, {})
        items.append({
            "id": m.get("id"), "thread_id": m.get("thread_id") or m.get("id"),
            "subject": m.get("subject") or "(no subject)",
            "snippet": _msg_text(m)[:180],
            "from": lead_email,
            "lead_email": lead_email,
            "name": who.get("name") or lead_email or "Reply", "company": who.get("company") or "",
            "lead_key": who.get("key") or "",
            "ts": m.get("created_at") or m.get("delivered_at") or "",
            "unread": not bool(m.get("is_read")),
        })
    items.sort(key=lambda x: x["ts"], reverse=True)
    return {"connected": True, "items": items}


@app.get("/api/inbox/thread")
def inbox_thread(campaign: str, thread_id: str):
    """Full conversation for one thread, oldest first."""
    cfg = _load(campaign)
    sid = _apollo_target(cfg)
    if not sid:
        return {"connected": False, "messages": []}
    try:
        raw = apollo_send.get_thread(thread_id)
    except Exception as e:
        return {"connected": False, "messages": [], "error": str(e)}
    msgs = []
    for m in raw:
        # Apollo message type: sent from a mailbox vs received from the lead
        received = bool(m.get("from_email")) and not m.get("email_account_id")
        msgs.append({
            "id": m.get("id"),
            "subject": m.get("subject") or "",
            "from": m.get("from_email") or "",
            "to": m.get("to_email") or "",
            "text": _msg_text(m),
            "ts": m.get("created_at") or m.get("delivered_at") or "",
            "direction": "in" if received else "out",
        })
    msgs.sort(key=lambda x: x["ts"])
    return {"connected": True, "messages": msgs}


@app.get("/api/analytics")
def analytics(campaign: str):
    """Delivery analytics from the Apollo sequence. connected=false when unwired."""
    cfg = _load(campaign)
    sid = _apollo_target(cfg)
    if not sid:
        return {"connected": False}
    try:
        a = apollo_send.sequence_stats(sid)
    except Exception as e:
        return {"connected": False, "error": str(e)}
    return {
        "connected": True,
        "sent": a.get("unique_delivered", 0),
        "opens": a.get("unique_opened", 0),
        "replies": a.get("unique_replied", 0),
        "bounced": a.get("unique_bounced", 0),
        "clicks": a.get("unique_clicked", 0),
    }


@app.get("/api/ab")
def ab(campaign: str):
    """A/B: reply rate for signal-led vs plain-control openers. Syncs replies from the
    Apollo inbox (match reply sender -> lead) so we can measure whether grounded signal
    openers actually lift replies — the core, currently-unproven product hypothesis."""
    cfg = _load(campaign)
    store = open_store()
    sid = _apollo_target(cfg)
    if sid:  # attribute Apollo replies to leads, then to their variant
        try:
            directory = _lead_directory(store, cfg["name"])
            for m in apollo_send.list_replies(sid):
                who = directory.get((m.get("from_email") or m.get("from_address") or "").lower())
                if who:
                    store.mark_replied(who["key"])
        except Exception:
            pass
    stats = store.ab_stats(cfg["name"])
    variants = {}
    for v, s in stats.items():
        base = s["sent"] or s["drafted"]
        variants[v] = {**s, "reply_rate": round(s["replied"] / base * 100, 1) if base else 0.0}
    return {"variants": variants, "experiment": bool((cfg.get("experiment") or {}).get("enabled"))}


class Decision(BaseModel):
    campaign: str
    key: str
    decision: str  # approve | reject


@app.post("/api/review/decision")
def decide(d: Decision):
    _load(d.campaign)
    store = open_store()
    val = "approved" if d.decision.lower().startswith("a") else "rejected"
    store.set_review(d.key, val)
    return {"key": d.key, "decision": val}


class LeadEmail(BaseModel):
    campaign: str
    key: str
    email: str


@app.post("/api/lead/email")
def set_lead_email(r: LeadEmail):
    """Set/fix a lead's email from the drawer, so a 'no email' lead can actually send."""
    _load(r.campaign)
    email = r.email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "that doesn't look like a valid email address")
    store = open_store()
    lead = store.get_lead(r.key)
    if not lead:
        raise HTTPException(404, "lead not found")
    lead.email = email
    store.update_lead(lead)
    return {"ok": True, "email": email, "verify": store.get_verify(email) or ""}


class EditReq(BaseModel):
    campaign: str
    key: str
    subject: str
    body: str


@app.post("/api/review/edit")
def edit(e: EditReq):
    _load(e.campaign)
    open_store().update_outbox(e.key, e.subject, e.body)  # marks edited=True; preserved on re-runs
    return {"ok": True, "key": e.key}


@app.post("/api/pull")
async def pull(campaign: str = Form(...), file: UploadFile = File(...), source: str = Form("csv")):
    cfg = _load(campaign)
    store = open_store()
    data = await file.read()
    tmp = os.path.join(tempfile.mkdtemp(), "upload.csv")
    with open(tmp, "wb") as f:
        f.write(data)
    leads_in = csv_source.from_csv(tmp)
    for lead in leads_in:
        lead.source = source
        if not lead.company_domain and lead.company:  # enrich missing domains (free, guarded)
            d = enrich.find_domain(lead.company)
            if d:
                lead.company_domain = d
        store.upsert_lead(lead, cfg["name"])
    return {"pulled": len(leads_in), "counts": store.counts(cfg["name"])}


class ApolloPull(BaseModel):
    campaign: str
    limit: int = 250


@app.post("/api/pull/apollo")
def pull_apollo(r: ApolloPull):
    """Pull leads straight from Apollo by the campaign's filters (needs a paid Apollo plan)."""
    cfg = _load(r.campaign)
    if not apollo.has_key():
        raise HTTPException(400, "APOLLO_API_KEY is not set. Add it to .env and restart the backend.")
    store = open_store()
    # Apollo ids already pulled into this campaign — skip them so a repeat pull
    # reveals only NEW contacts and never re-charges for ones you already have.
    known_ids = {(lead.raw or {}).get("id") for lead in store.leads(cfg["name"])}
    known_ids.discard(None)
    try:
        leads_in, credits = apollo.fetch_leads(cfg, limit=min(max(r.limit, 1), 2000), known_ids=known_ids)
    except Exception as e:
        raise HTTPException(400, str(e))
    for lead in leads_in:
        lead.source = "apollo"
        if not lead.company_domain and lead.company:  # enrich missing domains (free, guarded)
            d = enrich.find_domain(lead.company)
            if d:
                lead.company_domain = d
        store.upsert_lead(lead, cfg["name"])
    return {"pulled": len(leads_in), "credits_used": credits, "counts": store.counts(cfg["name"])}


class RunReq(BaseModel):
    campaign: str
    send: bool = False
    limit: int | None = None   # process at most N leads per run (None = all); guards cost


def _do_run(name: str, send: bool, limit: int | None):
    try:
        cfg = _load(name)
        store = open_store()
        pipeline.run(store, cfg, dry_run=not send, limit=limit, require_review=True)
        _runs[name] = {"running": False, "error": None, "summary": store.counts(cfg["name"])}
    except Exception as e:
        _runs[name] = {"running": False, "error": str(e), "summary": {}}


@app.post("/api/run")
def run(req: RunReq):
    if _runs.get(req.campaign, {}).get("running"):
        return {"started": False, "reason": "already running"}
    _runs[req.campaign] = {"running": True, "error": None, "summary": {}}
    threading.Thread(target=_do_run, args=(req.campaign, req.send, req.limit), daemon=True).start()
    return {"started": True}


@app.get("/api/run/status")
def run_status(campaign: str):
    return _runs.get(campaign, {"running": False, "error": None, "summary": {}})
