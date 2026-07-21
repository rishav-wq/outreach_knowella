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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, pipeline, tagging
from .engine import classify, personalize
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

CONFIG_DIR = "config"   # legacy seed source (committed campaigns + the CLI); runtime campaigns now live in Mongo
_runs: dict = {}  # campaign -> {running, error, summary}
_seeded = False   # one-time file→Mongo migration guard (per process)
REQUIRED_KEYS = ("name", "icp", "offer", "voice")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _seed_campaigns_once(store) -> None:
    """One-time migration: if Mongo has NO campaigns yet, import any committed
    config/*.yaml so an existing deployment doesn't come up empty. Runs at most
    once per process and never overwrites — afterward Mongo is the source of truth
    (deletes stick; new files are not auto-imported)."""
    global _seeded
    if _seeded:
        return
    _seeded = True
    try:
        if store.has_any_campaign():
            return
        for f in sorted(glob.glob(os.path.join(CONFIG_DIR, "*.yaml"))):
            slug = os.path.splitext(os.path.basename(f))[0]
            if slug.endswith(".example"):
                continue
            with open(f, encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            cfg.setdefault("name", slug)
            store.save_campaign(slug, cfg)
    except Exception:
        pass   # seeding is best-effort; never block the app on it


def _load(name: str) -> dict:
    """The campaign config, from Mongo (durable), validated + defaulted."""
    store = open_store()
    _seed_campaigns_once(store)
    cfg = store.get_campaign(name)
    if cfg is None:
        raise HTTPException(404, f"campaign '{name}' not found")
    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        raise HTTPException(500, f"campaign '{name}' is missing required keys: {missing}")
    for k, default in (("knowledge", []), ("models", {}), ("sending", {}),
                       ("research", {}), ("verify", {}), ("apollo", {}), ("experiment", {})):
        cfg.setdefault(k, default)
    return cfg


def _require_campaign(name: str) -> None:
    """404 if the campaign doesn't exist — for endpoints that don't need the cfg."""
    if not open_store().campaign_exists(name):
        raise HTTPException(404, f"campaign '{name}' not found")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/campaigns")
def campaigns():
    store = open_store()
    _seed_campaigns_once(store)
    return store.campaign_names()


class CampaignCreate(BaseModel):
    name: str
    icp: dict = {}
    apollo: dict = {}   # Apollo pull filters (keywords/exclude/etc.) — extends icp
    offer: dict = {}
    knowledge: list = []
    voice: dict = {}
    research: dict = {}
    verify: dict = {}
    sending: dict = {}
    sequence: dict = {}     # {steps: [{wait_days, template}]} — step 1 = first touch
    experiment: dict = {}   # {enabled, control_ratio} — wizard slider; defaulted if absent


@app.post("/api/campaigns")
def create_campaign(c: CampaignCreate):
    """Create a campaign config from the wizard. The slug is both filename and store key."""
    slug = _slug(c.name)
    if not slug:
        raise HTTPException(400, "campaign name must contain letters or numbers")
    store = open_store()
    if store.campaign_exists(slug):
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
    if c.apollo:  # only write the pull-filter block when the wizard supplied one
        cfg["apollo"] = c.apollo
    if c.sequence:  # sequence shape: how many emails, per-step template + wait
        cfg["sequence"] = c.sequence
    # Product defaults every campaign should ship with (wizard doesn't ask):
    # the A/B experiment (research: signal-opener lift is unproven — measure it),
    # the strong drafting model (flash drifts on tight style), and the sender
    # signature + opt-out (emails must never go out unsigned).
    cfg["experiment"] = c.experiment or {"enabled": True, "control_ratio": 0.2}
    cfg["models"] = {"personalize": {"provider": "gemini", "model": "gemini-2.5-pro"}}
    cfg["sender"] = {
        "closing": "Best,",
        "signature": "Sid Singh\nFounder & CEO\n+1.604.970.8236\nsid@knowella.com\nKnowella AI Inc.",
        "opt_out_line": 'If this isn\'t relevant, reply "no thanks" and I won\'t email again.',
    }
    store.save_campaign(slug, cfg)
    return {"created": slug}


@app.get("/api/campaign/config")
def campaign_config(campaign: str):
    """The raw campaign config (for settings display)."""
    return _load(campaign)


class CampaignUpdate(BaseModel):
    campaign: str
    icp: dict | None = None
    apollo: dict | None = None
    offer: dict | None = None
    knowledge: list | None = None
    voice: dict | None = None
    research: dict | None = None
    experiment: dict | None = None
    verify: dict | None = None
    sequence: dict | None = None
    sending: dict | None = None   # partial — merged over existing (protects ids/fields)


class CampaignRename(BaseModel):
    campaign: str
    new_name: str


@app.post("/api/campaign/rename")
def rename_campaign(r: CampaignRename):
    """Rename a campaign safely: the slug keys both the campaign config and every
    lead record, so this re-saves the config under the new slug AND re-keys the
    leads in one action, then removes the old campaign doc."""
    store = open_store()
    cfg = store.get_campaign(r.campaign)
    if cfg is None:
        raise HTTPException(404, f"campaign '{r.campaign}' not found")
    slug = _slug(r.new_name)
    if not slug:
        raise HTTPException(400, "campaign name must contain letters or numbers")
    if slug == r.campaign:
        return {"renamed": slug, "leads_moved": 0}
    if store.campaign_exists(slug):
        raise HTTPException(409, f"campaign '{slug}' already exists")
    cfg["name"] = slug
    store.save_campaign(slug, cfg)
    moved = store.rename_campaign(r.campaign, slug)   # re-keys the leads
    store.delete_campaign(r.campaign)
    _runs.pop(r.campaign, None)
    return {"renamed": slug, "leads_moved": moved}


@app.post("/api/campaign/update")
def update_campaign(u: CampaignUpdate):
    """Edit a campaign from the Settings screen. Sections replace; sending merges."""
    store = open_store()
    cfg = store.get_campaign(u.campaign)
    if cfg is None:
        raise HTTPException(404, f"campaign '{u.campaign}' not found")
    for k in ("icp", "apollo", "offer", "voice", "research", "experiment", "verify", "sequence"):
        v = getattr(u, k)
        if v is not None:
            cfg[k] = v
    if u.knowledge is not None:
        cfg["knowledge"] = u.knowledge
    if u.sending is not None:
        cfg.setdefault("sending", {}).update(u.sending)
    store.save_campaign(u.campaign, cfg)
    return cfg


class CampaignDelete(BaseModel):
    campaign: str


@app.post("/api/campaign/delete")
def delete_campaign(r: CampaignDelete):
    """Delete a campaign's config. Its leads are NOT touched — they stay in the
    database (visible in the Library) so nothing is lost; only the campaign
    definition is removed."""
    store = open_store()
    if not store.campaign_exists(r.campaign):
        raise HTTPException(404, f"campaign '{r.campaign}' not found")
    store.delete_campaign(r.campaign)
    _runs.pop(r.campaign, None)
    return {"deleted": r.campaign}


# --- sending health: DNS auth (SPF/DKIM/DMARC) + Apollo mailbox scorecards ----
_dns_cache: dict = {}   # domain -> checks (per process; DNS changes are rare)
_DKIM_SELECTORS = ["selector1", "selector2", "google", "k1", "k2", "mail", "zoho", "default", "dkim"]


def _txt_records(name: str) -> list[str]:
    """TXT lookup via Google DNS-over-HTTPS (no local resolver dependency)."""
    import httpx
    try:
        r = httpx.get("https://dns.google/resolve", params={"name": name, "type": "TXT"}, timeout=10)
        return [a.get("data", "").strip('"') for a in (r.json().get("Answer") or [])]
    except Exception:
        return []


def _domain_auth(domain: str) -> dict:
    """SPF / DKIM / DMARC presence for a sending domain (cached per process)."""
    if domain in _dns_cache:
        return _dns_cache[domain]
    spf = any("v=spf1" in t for t in _txt_records(domain))
    dmarc_recs = [t for t in _txt_records(f"_dmarc.{domain}") if "v=dmarc1" in t.lower()]
    dmarc_policy = ""
    if dmarc_recs:
        import re as _re
        m = _re.search(r"p=(\w+)", dmarc_recs[0])
        dmarc_policy = m.group(1) if m else ""
    dkim = False
    for sel in _DKIM_SELECTORS:
        if any("v=DKIM1" in t or "k=rsa" in t for t in _txt_records(f"{sel}._domainkey.{domain}")):
            dkim = True
            break
    out = {"spf": spf, "dkim": dkim, "dmarc": bool(dmarc_recs), "dmarc_policy": dmarc_policy}
    _dns_cache[domain] = out
    return out


@app.get("/api/health/sending")
def sending_health(campaign: str):
    """Deliverability panel: per-mailbox Apollo scorecards + DNS auth per domain +
    the campaign sequence's bounce rate (warn past the ~2% industry line)."""
    cfg = _load(campaign)
    try:
        boxes = apollo_send.mailbox_health()
    except Exception as e:
        return {"connected": False, "error": str(e)}
    for b in boxes:
        b["dns"] = _domain_auth(b["domain"])
    seq = {}
    sid = _apollo_target(cfg)
    if sid:
        try:
            a = apollo_send.sequence_stats(sid)
            delivered = a.get("unique_delivered", 0) or 0
            bounced = a.get("unique_bounced", 0) or 0
            attempted = delivered + bounced
            rate = (bounced / attempted * 100) if attempted else 0.0
            seq = {"delivered": delivered, "bounced": bounced,
                   "bounce_rate": round(rate, 1), "warn": rate > 2.0}
        except Exception:
            seq = {}
    return {"connected": True, "mailboxes": boxes, "sequence": seq}


class SuppressReq(BaseModel):
    value: str          # an email, or a whole domain like 'acme.com'
    reason: str = ""


@app.get("/api/suppression")
def suppression_list():
    """The global do-not-contact list (emails + domains)."""
    return {"items": open_store().list_suppressed()}


@app.post("/api/suppression")
def suppression_add(r: SuppressReq):
    v = (r.value or "").strip()
    if not v or (" " in v) or ("." not in v):
        raise HTTPException(400, "enter an email address or a domain like acme.com")
    store = open_store()
    store.suppress(v, r.reason or "added manually")
    return {"ok": True, "items": store.list_suppressed()}


@app.post("/api/suppression/remove")
def suppression_remove(r: SuppressReq):
    store = open_store()
    store.unsuppress(r.value)
    return {"ok": True, "items": store.list_suppressed()}


@app.get("/api/mailboxes")
def mailboxes(campaign: str | None = None):
    """The Apollo mailboxes you can send from, plus which one this campaign uses."""
    current = None
    if campaign:
        current = (_load(campaign).get("sending") or {}).get("mailbox_id")
    return {"mailboxes": apollo_send.list_mailboxes(), "current": current}


@app.get("/api/sequences")
def sequences(campaign: str | None = None):
    """The Apollo sequences approved leads can be added to, plus this campaign's current one."""
    current = None
    if campaign:
        current = (_load(campaign).get("sending") or {}).get("sequence_id")
    return {"sequences": apollo_send.list_sequences(), "current": current}


class SequenceCreate(BaseModel):
    name: str
    waits: list[int] | None = None   # days before each follow-up (one per follow-up step)


@app.post("/api/sequences/create")
def sequence_create(r: SequenceCreate):
    """Create a ready-to-use Apollo sequence from the wizard: one step per email on
    our merge fields (any count — waits sets the day gaps; default day-3 + day-7),
    24/7 schedule, stop-on-reply. The user still flips Apollo's Activate toggle
    once (not settable via API)."""
    name = (r.name or "").strip()
    if not name:
        raise HTTPException(400, "sequence name is required")
    try:
        return apollo_send.create_sequence(name, r.waits)
    except Exception as e:
        raise HTTPException(502, f"Apollo would not create the sequence: {e}")


class MailboxSet(BaseModel):
    campaign: str
    mailbox_id: str


def _set_config_mailbox(name: str, mailbox_id: str, email: str) -> None:
    """Set sending.mailbox_id on the campaign (in Mongo)."""
    store = open_store()
    cfg = store.get_campaign(name)
    if cfg is None:
        raise HTTPException(404, f"campaign '{name}' not found")
    cfg.setdefault("sending", {})["mailbox_id"] = mailbox_id
    store.save_campaign(name, cfg)


@app.post("/api/campaign/mailbox")
def set_campaign_mailbox(m: MailboxSet):
    """Choose which Apollo mailbox this campaign sends from."""
    _require_campaign(m.campaign)  # 404s if the campaign doesn't exist
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
            "variant": ob.get("variant", "signal"),
            "signature": signature,
            "followups": [{"step": n, "subject": ob.get(f"subject_{n}", ""), "body": ob.get(f"body_{n}", "")}
                          for n in sorted(int(k.rsplit("_", 1)[-1]) for k in ob
                                          if k.startswith("body_") and k.rsplit("_", 1)[-1].isdigit())
                          if ob.get(f"body_{n}")],
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


_LABEL_PRIORITY = ["opt_out", "interested", "not_interested", "ooo", "other"]


def _classify_inbound(store, cfg: dict, inbound: list[dict], lead_email: str, lead_key: str) -> str:
    """Label a conversation's inbound replies (classify new ones; cached per message).

    Side effects: opt_out auto-suppresses the sender; real replies mark the lead
    replied with their label (feeds A/B + positive-reply stats). Returns the
    conversation's label ('' when there are no replies).
    """
    if not inbound:
        return ""
    ids = [m.get("id") for m in inbound if m.get("id")]
    known = store.get_reply_classes(ids)
    labels = []
    for m in inbound:
        mid = m.get("id")
        label = known.get(mid)
        if not label:
            label = classify.classify_reply(_msg_text(m), cfg)
            if mid:
                store.save_reply_class(mid, m.get("from_email") or lead_email, label)
        labels.append(label)
    conv_label = next((l for l in _LABEL_PRIORITY if l in labels), "other")
    if conv_label == "opt_out" and lead_email and not store.is_suppressed(lead_email):
        store.suppress(lead_email, "opted out via reply (auto)")
        if lead_key:
            store.set_status(lead_key, "suppressed")
    if lead_key and conv_label != "ooo":   # an OOO auto-reply is not a real reply
        store.mark_replied(lead_key, conv_label)
    return conv_label


def _conversations(sid: str, cfg: dict) -> list[dict]:
    """Group the sequence's messages into conversations (one item per lead thread)."""
    raw = apollo_send.list_messages(sid)
    store = open_store()
    directory = _lead_directory(store, cfg["name"])
    convs: dict = {}
    for m in raw:
        cid = m.get("conversation_id") or m.get("provider_thread_id") or m.get("id")
        convs.setdefault(cid, []).append(m)
    items = []
    for cid, msgs in convs.items():
        msgs.sort(key=lambda m: m.get("created_at") or "")
        last = msgs[-1]
        inbound = [m for m in msgs if apollo_send.is_inbound(m)]
        first_out = next((m for m in msgs if not apollo_send.is_inbound(m)), None)
        # the lead's address: whoever we sent to (or, for replies, the sender)
        lead_email = ((first_out or {}).get("to_email") or (inbound[0].get("from_email") if inbound else "") or "").lower()
        who = directory.get(lead_email, {})
        label = _classify_inbound(store, cfg, inbound, lead_email, who.get("key") or "")
        # bounce handling: a bounced send marks the address undeliverable (blocks any
        # future send via the verification gate) and flags the lead
        bounced = any(m.get("bounce") for m in msgs if not apollo_send.is_inbound(m))
        if bounced and lead_email:
            store.save_verify(lead_email, "undeliverable")
            if who.get("key"):
                store.set_status(who["key"], "bounced")
        items.append({
            "bounced": bounced,
            "meeting": bool(who.get("key")) and bool(store.meeting_keys([who["key"]])),
            "thread_id": cid,
            "subject": (first_out or last).get("subject") or "(no subject)",
            "snippet": _msg_text(last)[:180],
            "lead_email": lead_email,
            "name": who.get("name") or (last.get("to_name") if not apollo_send.is_inbound(last) else "") or lead_email or "Conversation",
            "company": who.get("company") or "",
            "lead_key": who.get("key") or "",
            "mailbox": ((first_out or {}).get("from_email") or "").lower(),
            "has_reply": bool(inbound) or any(m.get("replied") for m in msgs),
            "label": label,
            "messages": len(msgs),
            "ts": last.get("created_at") or "",
            "unread": any(not m.get("is_read", True) for m in inbound),
        })
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items


@app.get("/api/inbox")
def inbox(campaign: str):
    """Conversations grouped per lead thread. campaign='__all__' returns the GLOBAL
    inbox: every campaign's sequence merged into one stream, items tagged with their
    campaign (shared sequences are read once, not duplicated)."""
    if campaign == "__all__":
        items, seen_seq, connected, err = [], set(), False, ""
        for name in campaigns():
            try:
                cfg = _load(name)
            except Exception:
                continue
            sid = _apollo_target(cfg)
            if not sid or sid in seen_seq:
                continue
            seen_seq.add(sid)
            try:
                its = _conversations(sid, cfg)
            except Exception as e:
                err = str(e)
                continue
            connected = True
            for i in its:
                i["campaign"] = name
            items += its
        items.sort(key=lambda x: x["ts"], reverse=True)
        mailboxes = sorted({i["mailbox"] for i in items if i["mailbox"]})
        out = {"connected": connected, "items": items, "mailboxes": mailboxes}
        if not connected and err:
            out["error"] = err
        return out

    cfg = _load(campaign)
    sid = _apollo_target(cfg)
    if not sid:
        return {"connected": False, "items": []}
    try:
        items = _conversations(sid, cfg)
    except Exception as e:
        return {"connected": False, "items": [], "error": str(e)}
    mailboxes = sorted({i["mailbox"] for i in items if i["mailbox"]})
    return {"connected": True, "items": items, "mailboxes": mailboxes}


@app.get("/api/inbox/thread")
def inbox_thread(campaign: str, thread_id: str):
    """Full conversation for one thread (conversation_id), oldest first."""
    cfg = _load(campaign)
    sid = _apollo_target(cfg)
    if not sid:
        return {"connected": False, "messages": []}
    try:
        raw = apollo_send.list_messages(sid)
    except Exception as e:
        return {"connected": False, "messages": [], "error": str(e)}
    msgs = []
    for m in raw:
        cid = m.get("conversation_id") or m.get("provider_thread_id") or m.get("id")
        if cid != thread_id:
            continue
        received = apollo_send.is_inbound(m)
        msgs.append({
            "id": m.get("id"),
            "subject": m.get("subject") or "",
            "from": m.get("from_email") or "",
            "to": m.get("to_email") or "",
            "text": _msg_text(m),
            "ts": m.get("created_at") or m.get("completed_at") or "",
            "direction": "in" if received else "out",
        })
    msgs.sort(key=lambda x: x["ts"])
    return {"connected": True, "messages": msgs}


@app.get("/api/analytics")
def analytics(campaign: str):
    """Delivery (Apollo sequence) + outcome analytics (positive replies, meetings).

    Outcomes come from our own store (classified replies + marked meetings), so they
    work even when the Apollo sequence is unwired.
    """
    cfg = _load(campaign)
    outcomes = open_store().outcome_stats(cfg["name"])
    sid = _apollo_target(cfg)
    if not sid:
        return {"connected": False, "outcomes": outcomes}
    try:
        a = apollo_send.sequence_stats(sid)
    except Exception as e:
        return {"connected": False, "outcomes": outcomes, "error": str(e)}
    return {
        "connected": True,
        "sent": a.get("unique_delivered", 0),
        "opens": a.get("unique_opened", 0),
        "replies": a.get("unique_replied", 0),
        "bounced": a.get("unique_bounced", 0),
        "clicks": a.get("unique_clicked", 0),
        "outcomes": outcomes,
    }


class MeetingReq(BaseModel):
    campaign: str
    key: str
    booked: bool = True


@app.post("/api/lead/meeting")
def lead_meeting(m: MeetingReq):
    """Mark (or unmark) a meeting booked with this lead — the end-goal metric."""
    _load(m.campaign)
    store = open_store()
    if m.booked:
        store.mark_meeting(m.key)
    else:
        store.unmark_meeting(m.key)
    return {"ok": True, "key": m.key, "booked": m.booked}


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
        variants[v] = {**s,
                       "reply_rate": round(s["replied"] / base * 100, 1) if base else 0.0,
                       "positive_rate": round(s.get("interested", 0) / base * 100, 1) if base else 0.0}
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


class ExcludeReq(BaseModel):
    campaign: str
    key: str


@app.post("/api/review/exclude")
def exclude_lead(r: ExcludeReq):
    """Drop a not-a-fit lead from this campaign: clears its drafts + review state and
    removes it from the pipeline, but KEEPS the lead (and its research) in the master
    library for future marketing. Not the same as reject, which keeps it in-campaign."""
    _load(r.campaign)
    store = open_store()
    if not store.get_lead(r.key):
        raise HTTPException(404, "lead not found")
    store.exclude_lead(r.key)
    return {"key": r.key, "status": "excluded"}


class BulkLeadReq(BaseModel):
    campaign: str
    keys: list[str]


@app.post("/api/leads/exclude")
def bulk_exclude(r: BulkLeadReq):
    """Bulk 'not a fit': remove the selected leads from the campaign (drafts cleared,
    dropped from the pipeline) but KEEP them in the marketing library for reuse."""
    _load(r.campaign)
    n = open_store().exclude_leads(r.keys)
    return {"excluded": n}


@app.post("/api/leads/delete")
def bulk_delete(r: BulkLeadReq):
    """Permanently delete the selected leads and all their data — gone everywhere,
    library included. For junk pulls we'll never use, even for marketing. Irreversible."""
    _load(r.campaign)
    n = open_store().delete_leads(r.keys)
    return {"deleted": n}


@app.get("/api/leads/all")
def all_leads():
    """The master leads library: every lead ever pulled, across ALL campaigns, with its
    persona bucket (from title) and topic tags (from the campaign it came in on). Leads
    are never deleted — excluding one from a campaign only clears its drafts and marks it
    'not a fit', but it stays here. The Leads tab is per-campaign; this is the whole pool."""
    store = open_store()
    _topic_cache: dict[str, list] = {}   # campaign slug -> topics, so we read each config once

    def topics_for(campaign: str, stored: list) -> list:
        if stored:
            return stored
        if campaign not in _topic_cache:
            try:
                _topic_cache[campaign] = tagging.topics_of(_load(campaign))
            except Exception:
                _topic_cache[campaign] = []
        return _topic_cache[campaign]

    rows = store.all_leads()
    for row in rows:
        row["function"] = tagging.function_of(row.get("title", ""))
        row["topics"] = topics_for(row.get("campaign", ""), row.get("topics") or [])
    return {"leads": rows, "function_labels": tagging.FUNCTION_LABELS}


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


class FollowupEditReq(BaseModel):
    campaign: str
    key: str
    step: int          # 2 or 3
    subject: str
    body: str


@app.post("/api/review/edit_followup")
def edit_followup(e: FollowupEditReq):
    if e.step not in (2, 3):
        raise HTTPException(400, "step must be 2 or 3")
    _load(e.campaign)
    open_store().update_followup(e.key, e.step, e.subject, e.body)
    return {"ok": True}


class RefineReq(BaseModel):
    campaign: str
    key: str
    instruction: str


@app.post("/api/review/refine")
def refine(r: RefineReq):
    """AI-tweak a draft: rewrite it per the user's instruction, kept grounded in the lead's facts."""
    cfg = _load(r.campaign)
    if not (r.instruction or "").strip():
        raise HTTPException(400, "instruction is empty")
    store = open_store()
    lead = store.get_lead(r.key)
    if not lead:
        raise HTTPException(404, "lead not found")
    ob = store.get_outbox(r.key)
    if not ob:
        raise HTTPException(400, "no draft to refine yet")
    res = store.get_research_any(r.key)
    draft, usage, model = personalize.refine_email(
        lead, res, cfg, ob.get("subject", ""), ob.get("body", ""), r.instruction)
    store.update_outbox(r.key, draft.subject, draft.body)  # marks edited=True; preserved on re-runs
    store.log_llm(r.key, "refine", model, usage)
    return {"subject": draft.subject, "body": draft.body}


@app.post("/api/pull")
async def pull(campaign: str = Form(...), file: UploadFile = File(...), source: str = Form("csv")):
    cfg = _load(campaign)
    store = open_store()
    data = await file.read()
    tmp = os.path.join(tempfile.mkdtemp(), "upload.csv")
    with open(tmp, "wb") as f:
        f.write(data)
    leads_in = csv_source.from_csv(tmp)
    topics = tagging.topics_of(cfg)   # library tags, stamped on each lead at pull
    skipped = 0
    for lead in leads_in:
        lead.source = source
        if lead.email and store.is_suppressed(lead.email):  # compliance: never re-import
            skipped += 1
            continue
        if not lead.company_domain and lead.company:  # enrich missing domains (free, guarded)
            d = enrich.find_domain(lead.company)
            if d:
                lead.company_domain = d
        store.upsert_lead(lead, cfg["name"], topics)
    return {"pulled": len(leads_in) - skipped, "suppressed": skipped, "counts": store.counts(cfg["name"])}


class ApolloPreview(BaseModel):
    icp: dict = {}
    apollo: dict = {}


@app.post("/api/preview/apollo")
def preview_apollo(r: ApolloPreview):
    """How many people match these audience filters in Apollo — free (search costs
    no credits; only revealing contacts does). Takes the filter blocks directly so
    the wizard can show a live count BEFORE the campaign exists, and so edits show
    the count for the form's current (unsaved) state. The number equals Apollo's
    own People-tab total for identical filters — a cross-check against their UI."""
    if not apollo.has_key():
        raise HTTPException(400, "APOLLO_API_KEY is not set. Add it to .env and restart the backend.")
    try:
        total = apollo.search_total({"icp": r.icp, "apollo": r.apollo})
    except Exception as e:
        raise HTTPException(502, str(e))
    return {"total": total}


@app.get("/api/apollo/schools")
def apollo_schools(q: str):
    """University-name typeahead for the alumni filter: resolves a typed name to
    Apollo school records (id + name) via the company-name search. The user picks
    the exact school — top hit isn't always right ('MIT' → MIT Technology Review)."""
    if not apollo.has_key():
        raise HTTPException(400, "APOLLO_API_KEY is not set. Add it to .env and restart the backend.")
    if len(q.strip()) < 3:
        return {"schools": []}
    try:
        return {"schools": apollo.search_schools(q.strip())}
    except Exception as e:
        raise HTTPException(502, str(e))


class LookalikeReq(BaseModel):
    campaign: str
    key: str          # lead key
    on: bool = True   # add (True) or remove (False) this lead as a lookalike seed


@app.post("/api/campaign/lookalike")
def toggle_lookalike(r: LookalikeReq):
    """Mark a lead as a lookalike seed: future Apollo pulls add `lookalike_person_ids`
    so the search returns people SIMILAR to your proven leads (live-verified — a
    Safety-Director-at-a-trucking-co seed returns other trucking safety directors).
    Seeds AND with the campaign's other filters. Stored as {id, label} in the
    config's apollo block; only Apollo-sourced leads carry a person id to seed from."""
    store = open_store()
    cfg = store.get_campaign(r.campaign)
    if cfg is None:
        raise HTTPException(404, f"campaign '{r.campaign}' not found")
    lead = store.get_lead(r.key)
    if not lead:
        raise HTTPException(404, "lead not found")
    pid = (lead.raw or {}).get("id")
    if not pid:
        raise HTTPException(400, "this lead has no Apollo person id (only Apollo-pulled leads can seed lookalikes)")
    ap = cfg.setdefault("apollo", {})
    seeds = [s for s in (ap.get("lookalike_seeds") or []) if s.get("id") != pid]
    if r.on:
        label = " · ".join(x for x in (lead.full_name, lead.company) if x) or pid
        seeds.append({"id": pid, "label": label})
    ap["lookalike_seeds"] = seeds
    store.save_campaign(r.campaign, cfg)
    return {"lookalike_seeds": seeds}


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
    topics = tagging.topics_of(cfg)   # library tags, stamped on each lead at pull
    skipped = 0
    for lead in leads_in:
        lead.source = "apollo"
        if lead.email and store.is_suppressed(lead.email):  # compliance: never re-import
            skipped += 1
            continue
        if not lead.company_domain and lead.company:  # enrich missing domains (free, guarded)
            d = enrich.find_domain(lead.company)
            if d:
                lead.company_domain = d
        store.upsert_lead(lead, cfg["name"], topics)
    return {"pulled": len(leads_in) - skipped, "suppressed": skipped,
            "credits_used": credits, "counts": store.counts(cfg["name"])}


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


# --- serve the built frontend (single-container deploy) ----------------------
# When web/dist exists (Docker build), this same server hosts the React app, so
# there's one origin (no CORS) and one URL. Registered last so /api routes win.
_WEB_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(_WEB_DIST):
    _assets = os.path.join(_WEB_DIST, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        """Serve a static file if it exists, else index.html (SPA + /sign-in fallback)."""
        if full_path.startswith("api/"):
            raise HTTPException(404, "not found")
        candidate = os.path.join(_WEB_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_WEB_DIST, "index.html"))
