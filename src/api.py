"""FastAPI backend — wraps the pipeline so the React UI can drive it over HTTP.

Run:  uvicorn src.api:app --reload --port 8000
The engine logic lives in pipeline/; this just exposes it as JSON endpoints.
"""
from __future__ import annotations

import glob
import hashlib
import hmac
import html
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
import re
import tempfile
import threading
import time

import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, marketing, pipeline, tagging, unsubscribe
from .engine import classify, personalize
from . import routing, signals
from .integrations import apollo, apollo_send, csv_source, email_verify, enrich, osha, postmark_send
from .models import Fact, Lead, Research
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
    # The LinkedIn-capture extension's popup calls the API from a chrome-extension://
    # origin (unknowable in advance — ids vary per install). Letting the browser make
    # the request is safe: those routes still authenticate via the capture token /
    # Clerk — CORS was never the security boundary, the token is.
    allow_origin_regex=r"^chrome-extension://.*$",
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_DIR = "config"   # legacy seed source (committed campaigns + the CLI); runtime campaigns now live in Mongo
_runs: dict = {}  # campaign -> {running, error, summary, started_at}
_run_threads: dict = {}  # campaign -> worker Thread (kept out of _runs so it stays JSON-serializable)
_seeded = False   # one-time file→Mongo migration guard (per process)
_leads_migrated = False   # one-time lead-key re-scoping guard (per process)
_sources_backfilled = False   # one-time attribution backfill guard (per process)
REQUIRED_KEYS = ("name", "icp", "offer", "voice")


def _migrate_leads_once(store) -> None:
    """Re-scope legacy lead keys to campaign-scoped ids, once per process. Runs at the
    _load choke point so it completes before any lead read/write in a fresh process."""
    global _leads_migrated
    if _leads_migrated:
        return
    _leads_migrated = True
    try:
        n = store.migrate_lead_keys()
        if n:
            print(f"[migrate] re-scoped {n} legacy lead(s) to campaign-scoped keys")
    except Exception as e:
        print(f"[migrate] lead re-key skipped: {e}")


def _backfill_sources_once(store) -> None:
    """Give the pre-attribution leads their source, once per process. Every lead we
    already have came from Apollo; recording that makes it the baseline every
    hand-engaged LinkedIn source gets measured against."""
    global _sources_backfilled
    if _sources_backfilled:
        return
    _sources_backfilled = True
    try:
        n = store.backfill_source_ids()
        if n:
            print(f"[migrate] attributed {n} existing lead(s) to their source")
    except Exception as e:
        print(f"[migrate] source backfill skipped: {e}")


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
    _migrate_leads_once(store)
    _backfill_sources_once(store)
    signals.start_poller(open_store, extra=[osha.poll])
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


# Knowella pinwheel mark (verbatim from web/src/components/Logo.jsx) for the
# standalone unsubscribe page, which the React app / its assets don't reach.
_PINWHEEL = (
    '<svg viewBox="0 0 32 32" width="30" height="30" aria-label="Knowella">'
    '<path fill="#87DD75" d="M13.2,16c0-4.5-2-8.4-5.3-10.7c-1.3-0.9-2.7-1.4-4-1.6c-0.5-0.1-0.9-0.1-1.4,0C2,3.8,1.6,4,1.2,4.3 C0.9,4.6,0.6,5,0.4,5.4C0.2,5.9,0.1,6.3,0.1,6.8c0,0.7,0.3,1.5,0.7,2c0.5,0.6,1.1,1,1.8,1.1c0.8,0.2,1.4,0.4,1.9,0.6 c0,0,3.4,1.4,3.5,5.2C8,15.9,8,16,8,16c0,0.1,0,0.1,0,0.2c-0.1,3.7-3.3,5.2-3.3,5.2S4,21.8,2.6,22.2c-0.7,0.1-1.3,0.5-1.8,1.1 c-0.5,0.6-0.7,1.3-0.7,2c0,0.5,0.1,0.9,0.3,1.4c0.2,0.4,0.5,0.8,0.9,1.1C1.6,28,2,28.2,2.5,28.3c0.5,0.1,0.9,0.1,1.4,0 c1.8-0.4,3.5-1.2,4.9-2.3C11.6,23.8,13.2,20.1,13.2,16z"/>'
    '<path fill="#6459FF" d="M16,18.8c-4.5,0-8.4,2-10.7,5.3c-0.9,1.3-1.3,2.7-1.6,4c-0.1,0.5-0.1,0.9,0,1.4c0.1,0.5,0.3,0.9,0.6,1.3 c0.3,0.4,0.7,0.7,1.1,0.9C5.9,31.9,6.4,32,6.9,32c0.7,0,1.4-0.3,2-0.7s1-1.1,1.1-1.8c0.2-0.8,0.4-1.5,0.6-2c0,0,1.4-3.4,5.2-3.5H16 c0.1,0,0.1,0,0.2,0c3.7,0.1,5.2,3.3,5.2,3.3s0.5,0.7,0.8,2.2c0.1,0.7,0.5,1.3,1.1,1.8c0.6,0.5,1.3,0.7,2,0.7l0,0 c0.5,0,0.9-0.1,1.4-0.3c0.4-0.2,0.8-0.5,1.1-0.9c0.3-0.4,0.5-0.8,0.6-1.3c0.1-0.5,0.1-0.9,0-1.4c-0.4-1.8-1.2-3.5-2.3-4.9 C23.8,20.4,20.1,18.8,16,18.8z"/>'
    '<path fill="#FFD600" d="M18.8,16c0,4.5,2,8.4,5.3,10.7c1.3,0.9,2.7,1.4,4,1.6c0.5,0.1,0.9,0.1,1.4,0c0.5-0.1,0.9-0.3,1.3-0.6 c0.4-0.3,0.7-0.7,0.9-1.1c0.2-0.4,0.3-0.9,0.3-1.4c0-0.7-0.3-1.5-0.7-2c-0.5-0.6-1.1-1-1.8-1.1c-0.8-0.2-1.4-0.4-1.9-0.6 c0,0-3.4-1.4-3.5-5.2c0-0.1,0-0.1,0-0.2c0-0.1,0-0.1,0-0.2c0.1-3.7,3.3-5.2,3.3-5.2s0.7-0.5,2.2-0.8c0.7-0.1,1.3-0.5,1.8-1.1 c0.5-0.6,0.7-1.3,0.7-2c0-0.5-0.1-0.9-0.3-1.4c-0.2-0.4-0.5-0.8-0.9-1.1C30.4,4,30,3.8,29.5,3.7s-0.9-0.1-1.4,0 c-1.8,0.4-3.5,1.2-4.9,2.3C20.4,8.2,18.8,11.9,18.8,16z"/>'
    '<path fill="#04B492" d="M16,13.2c4.5,0,8.4-2,10.7-5.3c0.9-1.3,1.3-2.7,1.6-4c0.1-0.5,0.1-0.9,0-1.4c-0.1-0.5-0.3-0.9-0.6-1.3 c-0.3-0.4-0.7-0.7-1.1-0.9C26.1,0.1,25.6,0,25.1,0c-0.7,0-1.4,0.3-2,0.7c-0.6,0.5-1,1.1-1.1,1.8c-0.2,0.8-0.4,1.5-0.6,2 c0,0-1.4,3.4-5.2,3.5C16.1,8,16,8,16,8c-0.1,0-0.1,0-0.2,0c-3.7-0.1-5.2-3.3-5.2-3.3S10.2,4,9.9,2.5C9.7,1.8,9.3,1.2,8.8,0.7 C8.2,0.3,7.5,0,6.8,0l0,0C6.3,0,5.9,0.1,5.4,0.3C5,0.5,4.6,0.8,4.3,1.2C4,1.6,3.8,2,3.7,2.4c-0.1,0.5-0.1,0.9,0,1.4 C4.1,5.6,4.9,7.3,6,8.7C8.2,11.6,11.9,13.2,16,13.2z"/></svg>')

_CHECK = ('<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
          'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>')
_CROSS = ('<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
          'stroke-width="2.4" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>')


def _unsubscribe_page(ok: bool) -> str:
    heading = "You’re unsubscribed" if ok else "Link not valid"
    msg = ("You won’t receive any more emails from us. Sorry for the interruption."
           if ok else
           "This unsubscribe link couldn’t be verified — it may be old or altered. If you’re "
           "still getting emails, reply “unsubscribe” to one and we’ll remove you.")
    return ("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Unsubscribe · Knowella</title>
<style>
:root{color-scheme:light dark}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;
background:#f6fafa;color:#242a32;font-family:'Segoe UI',system-ui,-apple-system,Roboto,sans-serif}
.card{background:#fff;border:1px solid #e6ecf1;border-radius:16px;
padding:40px 36px 30px;max-width:430px;width:100%;text-align:center}
.brand{display:flex;justify-content:center;align-items:center;gap:9px;margin-bottom:22px}
.brand b{font-size:16px;font-weight:600;letter-spacing:-.01em}
.brand i{font-style:normal;font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:#96a1af;font-weight:600}
.mark{width:54px;height:54px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;margin-bottom:18px;background:#e6f8f4;color:#04b492}
.mark.bad{background:#f0f1ec;color:#96a1af}
h1{margin:0 0 10px;font-size:21px;font-weight:700;letter-spacing:-.02em}
p{margin:0;color:#64707c;line-height:1.65;font-size:14px}
.foot{margin-top:24px;font-size:11px;color:#aab3bc;letter-spacing:.04em}
@media(prefers-color-scheme:dark){body{background:#0d1411;color:#eef0f4}
.card{background:#161d1a;border-color:#28322d}
p{color:#9aa5ac}.mark.bad{background:#222b27}}
</style></head><body><div class="card">
<div class="brand">__PINWHEEL__<b>Knowella</b><i>Outreach</i></div>
<div class="mark __BAD__">__ICON__</div>
<h1>__HEADING__</h1><p>__MSG__</p>
<div class="foot">Knowella AI Inc.</div>
</div></body></html>""".replace("__PINWHEEL__", _PINWHEEL)
        .replace("__BAD__", "" if ok else "bad").replace("__ICON__", _CHECK if ok else _CROSS)
        .replace("__HEADING__", heading).replace("__MSG__", msg))


@app.get("/api/unsubscribe")
def unsubscribe_link(t: str = ""):
    """Public one-click unsubscribe (linked from every email footer). Verifies the
    token, adds the address to the global do-not-contact list, and shows a branded
    confirmation page. No auth (see auth._OPEN_API_PATHS)."""
    email = unsubscribe.email_from_token(t)
    if email:
        open_store().suppress(email, reason="unsubscribed via email link")
    return HTMLResponse(_unsubscribe_page(bool(email)))


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


def _stop_sequenced(store, value: str) -> int:
    """Suppression's second half: for a just-suppressed email or domain, STOP the
    remaining scheduled sequence emails of everyone it covers, inside Apollo.
    (Our list gates pull/pipeline/send, but Apollo drips already-enrolled contacts
    autonomously — 'ff Venture Capital said no' must also silence their follow-ups.)
    Returns how many enrolled contacts were stopped."""
    v = (value or "").strip().lower().lstrip("@")
    if not v:
        return 0
    is_domain = "@" not in v
    by_campaign: dict[str, list[str]] = {}
    for d in store.db.leads.find({}):
        email = ((d.get("lead") or {}).get("email") or "").strip().lower()
        if not email:
            continue
        if not (email.rsplit("@", 1)[-1] == v if is_domain else email == v):
            continue
        send = store.db.sends.find_one({"_id": d["_id"]})
        cid = (send or {}).get("platform_id")
        if cid:
            by_campaign.setdefault(d.get("campaign") or "", []).append(cid)
        store.set_status(d["_id"], "suppressed")
    stopped = 0
    for camp, cids in by_campaign.items():
        try:
            seq = ((store.get_campaign(camp) or {}).get("sending") or {}).get("sequence_id")
            stopped += apollo_send.stop_contacts(seq, cids)
        except Exception as e:
            logging.getLogger("uvicorn.error").warning("[suppress] couldn't stop %s in Apollo (%s): %s", camp, cids, e)
    return stopped


@app.post("/api/suppression")
def suppression_add(r: SuppressReq):
    v = (r.value or "").strip()
    if not v or (" " in v) or ("." not in v):
        raise HTTPException(400, "enter an email address or a domain like acme.com")
    store = open_store()
    store.suppress(v, r.reason or "added manually")
    stopped = _stop_sequenced(store, v)
    return {"ok": True, "stopped_in_apollo": stopped, "items": store.list_suppressed()}


@app.post("/api/suppression/remove")
def suppression_remove(r: SuppressReq):
    store = open_store()
    store.unsuppress(r.value)
    return {"ok": True, "items": store.list_suppressed()}


def _mailbox_ids(send_cfg: dict) -> list[str]:
    """A campaign's send-from mailbox ids as a list (back-compat with the old single
    sending.mailbox_id)."""
    return send_cfg.get("mailbox_ids") or ([send_cfg["mailbox_id"]] if send_cfg.get("mailbox_id") else [])


@app.get("/api/mailboxes")
def mailboxes(campaign: str | None = None):
    """The Apollo mailboxes you can send from, plus which ones this campaign uses.
    `current_ids` is the full set (campaigns can rotate across several); `current`
    is the first, kept for older callers."""
    ids = []
    if campaign:
        ids = _mailbox_ids(_load(campaign).get("sending") or {})
    # carry each mailbox's guard state so the picker can show WHY one is unusable
    boxes = apollo_send.list_mailboxes()
    try:
        health = {m["id"]: m for m in apollo_send.mailbox_health()}
        sent = open_store().mailbox_sends_today()
        for b in boxes:
            h = health.get(b["id"]) or {}
            cap = apollo_send.effective_cap(h) if h else 0
            used = sent.get(b["id"], 0)
            b.update({
                "placement": h.get("placement", ""), "warmup": h.get("warmup_score"),
                "cap": cap, "sent_today": used,
                "protected": apollo_send.is_protected(b["email"]),
                "blocked": bool(h) and (cap <= 0 or used >= cap),
            })
    except Exception:
        pass   # health is advisory — never break the picker over it
    return {"mailboxes": boxes, "current_ids": ids, "current": ids[0] if ids else None}


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
    mailbox_ids: list[str] = []


@app.post("/api/campaign/mailbox")
def set_campaign_mailbox(m: MailboxSet):
    """Choose which Apollo mailbox(es) this campaign sends from — a list, since sends
    rotate across them for deliverability. mailbox_id (singular) is kept as the first,
    for older callers."""
    store = open_store()
    cfg = store.get_campaign(m.campaign)
    if cfg is None:
        raise HTTPException(404, f"campaign '{m.campaign}' not found")
    valid = {b["id"] for b in apollo_send.list_mailboxes()}
    ids = [i for i in m.mailbox_ids if i in valid]
    if len(ids) != len(m.mailbox_ids):
        raise HTTPException(400, "one or more mailboxes aren’t among your Apollo email accounts")
    send = cfg.setdefault("sending", {})
    send["mailbox_ids"] = ids
    send["mailbox_id"] = ids[0] if ids else ""   # back-compat primary
    store.save_campaign(m.campaign, cfg)
    return {"mailbox_ids": ids}


@app.get("/api/status")
def status(campaign: str, light: bool = False):
    """light=1: skip the token aggregation — the header polls this every 15s and
    its pills don't show tokens; the full version is for the Overview."""
    cfg = _load(campaign)
    store = open_store()
    send_cfg = cfg.get("sending") or {}
    # Sending goes through Apollo sequences: needs the key + a sequence + a mailbox.
    # send_block names the FIRST missing piece so the UI can say exactly why send is off.
    mailbox_ids = _mailbox_ids(send_cfg)
    if not os.environ.get("APOLLO_API_KEY"):
        send_block = "Apollo isn’t connected — no API key on the server."
    elif not send_cfg.get("sequence_id"):
        send_block = "No Apollo sequence wired — set one in this campaign’s Settings › Send step."
    elif not mailbox_ids:
        send_block = "No sending mailbox chosen — pick one above or in Settings › Send."
    else:
        send_block = ""
    sendable = not send_block
    return {
        "counts": store.counts(cfg["name"]),
        "tokens": {} if light else store.token_totals(cfg["name"]),
        "sendable": sendable,
        "send_block": send_block,
        "mailbox_id": mailbox_ids[0] if mailbox_ids else "",
        "mailbox_ids": mailbox_ids,
        "guardrails": {
            "daily_cap": 0,   # app no longer caps sends — Apollo paces delivery at its own per-mailbox daily limit
            "sent_today": store.sent_today(cfg["name"]),
            "window": send_cfg.get("window") or {},
        },
        "apollo_rate": _apollo_rate_summary(),
        # Signals is campaign-independent, but the count rides along here because the
        # header already polls this every 15s — nobody opens a tab that doesn't say
        # it has something waiting.
        "signals_open": store.signal_counts().get("new", 0),
    }


def _apollo_rate_summary() -> dict:
    """Apollo API quota state, harvested passively from response headers (per endpoint,
    hourly windows). 'worst' = the endpoint with the least hourly budget left — the one
    that will stop a big send. Entries older than the current hour window are dropped."""
    now = datetime.now(timezone.utc)
    fresh: dict = {}
    for path, e in apollo_send.RATE_LIMITS.items():
        try:
            seen = datetime.fromisoformat(e["at"])
        except (KeyError, ValueError):
            continue
        # short shelf life: Apollo's hourly window resets behind our back, so a
        # 50-minute-old "0 left" is a lie — show nothing rather than stale numbers
        if now - seen < timedelta(minutes=10):
            fresh[path] = e
    worst = None
    for path, e in fresh.items():
        left = e.get("hourly_left")
        if left is not None and (worst is None or left < worst["left"]):
            worst = {"path": path, "left": left, "limit": e.get("hourly_limit")}
    return {"endpoints": fresh, "worst": worst}


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
    verbatim = pipeline._is_verbatim(cfg)   # AI off + template: shown as-is, no A/B badge
    # batched lookups: per-lead queries over a remote Mongo made a 483-deep queue
    # cost ~2,000 sequential round trips
    leads = store.leads(cfg["name"], "queued")
    keys = [l.key for l in leads]
    outboxes = store.get_outboxes(keys)
    decisions = store.get_reviews(keys)
    facts_map = store.get_research_facts(keys)
    verifies = store.get_verifies([l.email for l in leads if l.email])
    out = []
    for lead in leads:
        ob = outboxes.get(lead.key)
        if not ob:
            continue
        facts = [{"claim": f.get("claim", ""), "quote": f.get("quote", ""),
                  "source_url": f.get("source_url", ""), "source_type": f.get("source_type", ""),
                  "published": f.get("published")}
                 for f in facts_map.get(lead.key, [])]
        out.append({
            "key": lead.key, "name": lead.full_name, "company": lead.company,
            "title": lead.title, "source": lead.source,
            "verdict": ob["verdict"], "subject": ob["subject"], "body": ob["body"],
            "variant": ob.get("variant", "signal"), "verbatim": verbatim,
            "signature": signature,
            "followups": [{"step": n, "subject": ob.get(f"subject_{n}", ""), "body": ob.get(f"body_{n}", "")}
                          for n in sorted(int(k.rsplit("_", 1)[-1]) for k in ob
                                          if k.startswith("body_") and k.rsplit("_", 1)[-1].isdigit())
                          if ob.get(f"body_{n}")],
            "facts": facts, "decision": decisions.get(lead.key, ""),
            "edited": bool(ob.get("edited")),
            "email": lead.email,
            "verify": verifies.get(lead.email, "") if lead.email else "",
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


def _html_to_text(s: str) -> str:
    """Convert Apollo's HTML email body to plain text WITH line breaks preserved. Apollo's own
    body_text flattens the mailbox signature's block/<br> tags onto one line; we render the
    result in a <pre>, so we turn those block boundaries back into newlines ourselves."""
    if not s:
        return ""
    s = re.sub(r"(?i)<\s*br\s*/?>", "\n", s)                             # <br> -> newline
    s = re.sub(r"(?i)</\s*(div|p|li|tr|h[1-6]|blockquote)\s*>", "\n", s)  # end of a block -> newline
    s = re.sub(r"(?i)<\s*(div|p|li|tr|h[1-6]|blockquote)[^>]*>", "", s)   # drop the opening block tag
    s = re.sub(r"(?s)<[^>]+>", "", s)                                     # strip any remaining tags
    s = html.unescape(s)                                                 # &amp; -> &, &nbsp; -> space
    s = "\n".join(ln.rstrip() for ln in s.split("\n"))                   # trim trailing spaces per line
    return re.sub(r"\n{3,}", "\n\n", s).strip()                          # collapse runaway blank lines


def _msg_text(m: dict) -> str:
    b = m.get("body")
    if isinstance(b, dict):
        b = b.get("html") or b.get("text") or ""
    b = b or ""
    # Apollo populates body / body_text / body_html inconsistently per message — and
    # 'body' is sometimes only a SNIPPET. Convert the HTML ourselves (their plaintext
    # collapses the signature onto one line) and return the LONGEST candidate, so a
    # snippet field can never shadow the full message.
    html_body = m.get("body_html") or (b if ("<" in b and ">" in b) else "")
    candidates = [
        _html_to_text(html_body) if html_body else "",
        (b if not ("<" in b and ">" in b) else "").strip(),
        (m.get("body_text") or "").strip(),
    ]
    return max(candidates, key=len)


_SENT_STATUSES = {"completed", "delivered", "sent", "opened", "clicked",
                  "replied", "bounced", "hard_bounced", "soft_bounced"}


def _msg_sent(m: dict) -> bool:
    """True when Apollo has actually SENT this message (vs still scheduled/queued) — so we only
    preview staged copy for not-yet-sent messages and never mask a genuinely empty send."""
    s = (m.get("email_status") or m.get("status") or m.get("mailing_status") or "").lower()
    return s in _SENT_STATUSES


def _fill_scheduled(store, lead_key: str, msgs: list[dict]) -> None:
    """Apollo drip-sends a sequence, so most steps sit 'scheduled' with only an empty HTML
    skeleton for a body until it sends them. For those NOT-YET-SENT outbound messages, show the
    copy we STAGED (the outbox), matched by step order, instead of a blank bubble — the user
    sees what WILL go out. Sent messages are left exactly as Apollo rendered them, so a
    genuinely empty send is never hidden. Mutates msgs; each dict needs 'direction', 'text',
    'subject', and 'sent'."""
    if not lead_key:
        return
    ob = store.get_outbox(lead_key) or {}
    if not ob:
        return
    step = 0
    for m in msgs:
        if m.get("direction") != "out":
            continue
        step += 1
        staged = (ob.get("body") if step == 1 else ob.get(f"body_{step}", "")) or ""
        if m.get("sent"):
            # Apollo TRUNCATES the stored body once a thread is replied to (live-verified:
            # every body field cut mid-sentence). When our sent copy is clearly longer,
            # show it — visibly tagged, so a genuinely broken send is never masked.
            if m.get("text") and staged and len(staged) > len(m["text"]) + 20:
                m["text"] = staged
                m["restored"] = True
            continue
        if not m.get("text"):
            if staged:
                m["text"] = staged
                m["scheduled"] = True           # a preview of a not-yet-sent message
        if not m.get("subject") or m.get("subject") == "(no subject)":
            m["subject"] = (ob.get("subject") if step == 1 else ob.get(f"subject_{step}", "")) or m.get("subject") or ""


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
        _stop_sequenced(store, lead_email)   # also cancel their remaining Apollo follow-ups
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
    # batched: per-conversation outbox/meeting lookups were 2 round trips × N convos
    all_keys = [v["key"] for v in directory.values() if v.get("key")]
    outboxes = store.get_outboxes(all_keys)
    met = store.meeting_keys(all_keys)
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
        # Apollo's messages API returns ONLY outbound sends (live-verified 2026-07-30:
        # 234/234 type=outreach_automatic_email) — a reply exists solely as replied=True
        # on our own message. So replies are counted from that flag; without the reply
        # text they can't be sentiment-classified, so they land as 'other' in outcomes.
        out_replied = any(m.get("replied") for m in msgs if not apollo_send.is_inbound(m))
        if out_replied and not inbound and who.get("key") and not label:
            store.mark_replied(who["key"], "other")
        # bounce handling: a bounced send marks the address undeliverable (blocks any
        # future send via the verification gate) and flags the lead
        bounced = any(m.get("bounce") for m in msgs if not apollo_send.is_inbound(m))
        if bounced and lead_email:
            store.save_verify(lead_email, "undeliverable")
            if who.get("key"):
                store.set_status(who["key"], "bounced")
        # scheduled sends aren't rendered by Apollo yet — fall back to our staged copy so the
        # list shows the subject/snippet instead of "(no subject)"/blank.
        ob = outboxes.get(who.get("key"))
        out_steps = sum(1 for mm in msgs if not apollo_send.is_inbound(mm))
        subject = (first_out or last).get("subject") or (ob or {}).get("subject") or "(no subject)"
        snippet = _msg_text(last)
        if not snippet and ob and not apollo_send.is_inbound(last) and not _msg_sent(last):
            snippet = (ob.get("body") if out_steps <= 1 else ob.get(f"body_{out_steps}", "")) or ""
        items.append({
            "bounced": bounced,
            "meeting": who.get("key") in met,
            "thread_id": cid,
            "subject": subject,
            "snippet": snippet[:180],
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
            "sent": _msg_sent(m),
        })
    msgs.sort(key=lambda x: x["ts"])
    # scheduled sends Apollo hasn't rendered yet: show the staged copy, not a blank bubble
    store = open_store()
    lead_email = next((x["to"] for x in msgs if x["direction"] == "out" and x.get("to")), "")
    key = _lead_directory(store, cfg["name"]).get(lead_email.lower(), {}).get("key", "") if lead_email else ""
    _fill_scheduled(store, key, msgs)
    # Apollo's API never returns the reply message itself — only replied=True on our
    # send. Surface the reply honestly as a marker instead of showing nothing.
    replied_flag = any(m.get("replied") for m in raw
                       if (m.get("conversation_id") or m.get("provider_thread_id") or m.get("id")) == thread_id
                       and not apollo_send.is_inbound(m))
    if replied_flag and not any(x["direction"] == "in" for x in msgs):
        msgs.append({
            "id": "reply-marker", "direction": "in", "note": True, "sent": True,
            "subject": "", "from": lead_email, "to": "",
            "text": "They replied ✓ — Apollo’s API doesn’t share the reply text, so read it in Apollo or the sending mailbox. It’s already counted in your reply stats.",
            "ts": (msgs[-1]["ts"] if msgs else ""),
        })
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


class ApproveAllReq(BaseModel):
    campaign: str


@app.post("/api/review/approve_all")
def approve_all(r: ApproveAllReq):
    """Bulk-approve every pending, sendable draft in the review queue — the fast path for
    verbatim campaigns where every draft is the same template. Leaves explicit rejections
    untouched, and skips leads with no draft or no email (they could never send anyway)."""
    cfg = _load(r.campaign)
    store = open_store()
    n = 0
    for lead in store.leads(cfg["name"], "queued"):
        if store.get_review(lead.key) == "rejected":
            continue
        if not lead.email or not store.get_outbox(lead.key):
            continue
        store.set_review(lead.key, "approved")
        n += 1
    return {"approved": n}


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
    engaged = store.engagement_by_email()   # marketing intent: opened/clicked any blast
    for row in rows:
        row["function"] = tagging.function_of(row.get("title", ""))
        row["topics"] = topics_for(row.get("campaign", ""), row.get("topics") or [])
        e = engaged.get((row.get("email") or "").lower(), {})
        row["engagement"] = "clicked" if e.get("clicked") else ("opened" if e.get("opened") else "")
    return {"leads": rows, "function_labels": tagging.FUNCTION_LABELS}


class AudienceFilter(BaseModel):
    topics: list[str] = []
    statuses: list[str] = []
    exclude_sent: bool = False
    engagement: str = ""   # '' | 'opened' | 'clicked' — warm-slice narrowing


class PromoteReq(BaseModel):
    keys: list[str]
    campaign: str


@app.post("/api/library/promote")
def promote_leads(r: PromoteReq):
    """The flywheel's return path: move Library people (e.g. blast clickers) into a
    sales campaign as fresh 'new' leads — the normal pipeline (research → draft →
    review) takes over from there. Dedup is upsert_lead's job; suppressed skipped."""
    cfg = _load(r.campaign)
    store = open_store()
    topics = tagging.topics_of(cfg)
    added = skipped = 0
    for key in r.keys[:500]:
        d = store.db.leads.find_one({"_id": key})
        if not d:
            continue
        lead = Lead.model_validate(d["lead"])
        if lead.email and store.is_suppressed(lead.email):
            skipped += 1
            continue
        lead.stored_key = ""   # re-key into the target campaign's scope
        store.upsert_lead(lead, cfg["name"], topics)
        added += 1
    return {"added": added, "suppressed": skipped, "counts": store.counts(cfg["name"])}


# --- saved audiences: named filters, resolved live at every use ----------------
@app.get("/api/audiences")
def list_audiences():
    store = open_store()
    out = []
    for a in store.list_audiences():
        out.append({"id": a["_id"], "name": a.get("name", ""), "filter": a.get("filter") or {},
                    "count": len(store.audience_leads(a.get("filter") or {}))})
    return out


class AudienceCreate(BaseModel):
    name: str
    filter: AudienceFilter


@app.post("/api/audiences")
def create_audience(r: AudienceCreate):
    if not r.name.strip():
        raise HTTPException(400, "name is required")
    return {"id": open_store().create_audience(r.name.strip(), r.filter.model_dump())}


@app.delete("/api/audiences/{aid}")
def delete_audience(aid: str):
    open_store().delete_audience(aid)
    return {"ok": True}


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

    # Follow-ups are written FROM the first email, so a revise must regenerate them
    # too — otherwise they'd still reference the pre-revise draft. (update_outbox set
    # edited=True, so the pipeline won't regenerate them; we do it here.)
    variant = ob.get("variant", "signal")
    fu_steps = pipeline.followup_steps(cfg)
    followups = []
    if fu_steps:
        bodies, fu_usage, fu_model = personalize.write_followups(
            lead, res, cfg, draft.subject, draft.body, fu_steps, variant)
        if all(bodies):
            fuh = pipeline.hash_inputs("fu-rev3", draft.subject, draft.body, variant,
                                       [(s["wait_days"], s["template"], s["subject"]) for s in fu_steps])
            store.save_followups(
                r.key, [{"subject": s["subject"] or f"Re: {draft.subject}", "body": b}
                        for s, b in zip(fu_steps, bodies)], fuh)
            store.log_llm(r.key, "followups", fu_model, fu_usage)
    ob2 = store.get_outbox(r.key) or {}
    followups = [{"step": n, "subject": ob2.get(f"subject_{n}", ""), "body": ob2.get(f"body_{n}", "")}
                 for n in sorted(int(k.rsplit("_", 1)[-1]) for k in ob2
                                 if k.startswith("body_") and k.rsplit("_", 1)[-1].isdigit())
                 if ob2.get(f"body_{n}")]
    return {"subject": draft.subject, "body": draft.body, "followups": followups}


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
    src_id = store.upsert_source(f"CSV import ({source})", "import")
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
        store.upsert_lead(lead, cfg["name"], topics, source_id=src_id)
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


# --- LinkedIn commenter capture (browser extension) ---------------------------
# The extension reads commenters off a post YOU are viewing (name + profile URL +
# headline — LinkedIn as a pointer only) and posts them here; all contact data
# comes from Apollo's database. It authenticates with a per-user capture token
# (Clerk sessions don't travel into extensions); only its SHA-256 hash is stored.
_CAPTURE_TOKEN_KEY = "linkedin_capture_token_sha256"


def _capture_auth(request: Request) -> None:
    """Allow either a valid capture token (the extension) or a normal Clerk session
    (the web app / open local dev). 401 otherwise."""
    tok = request.headers.get("x-capture-token") or ""
    if tok:
        store = open_store()
        h = hashlib.sha256(tok.encode()).hexdigest()
        if store.find_capture_token(h):     # per-person tokens
            return
        legacy = store.get_setting(_CAPTURE_TOKEN_KEY)   # the old single shared token
        if legacy and hmac.compare_digest(h, legacy):
            return
        raise HTTPException(401, "invalid capture token — generate one in Settings and paste it into the extension")
    if auth.enabled() and not getattr(request.state, "user", None):
        raise HTTPException(401, "missing capture token")


# --- marketing engine (Postmark, broadcast stream) -----------------------------
@app.get("/api/marketing/status")
def marketing_status():
    return {"connected": postmark_send.has_key(), "from": postmark_send.from_address(),
            "stream": os.environ.get("POSTMARK_STREAM", "broadcast")}


class MarketingTest(BaseModel):
    to: str


@app.post("/api/marketing/test")
def marketing_test(r: MarketingTest):
    """Prove the marketing pipe end to end with one email to yourself — batching,
    the broadcast stream, and the verified sender, before any audience exists."""
    to = (r.to or "").strip()
    if "@" not in to:
        raise HTTPException(400, "enter a valid email address")
    try:
        res = postmark_send.send_batch([{
            "to": to,
            "subject": "Knowella Outreach — marketing pipe test",
            "text_body": ("Hi,\n\nThis is a test from Knowella Outreach's marketing engine "
                          "(Postmark, broadcast stream).\n\nIf you're reading this, the pipe works: "
                          "batching, the message stream, and your verified sender are all wired.\n\n"
                          "— Knowella Outreach"),
        }])
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    first = res[0] if res else {}
    if first.get("ErrorCode"):
        raise HTTPException(502, f"Postmark rejected it: {first.get('Message')}")
    return {"ok": True, "message_id": first.get("MessageID", "")}


class BlastBody(BaseModel):
    name: str
    subject: str
    body: str
    audience: AudienceFilter = AudienceFilter()


def _blast_out(b: dict) -> dict:
    return {"id": b["_id"], "name": b.get("name", ""), "subject": b.get("subject", ""),
            "body": b.get("body", ""), "audience": b.get("audience") or {},
            "status": b.get("status", "draft"), "stats": b.get("stats") or {},
            "progress": b.get("progress") or {}, "error": b.get("error", ""),
            "created_at": b.get("created_at", ""), "sent_at": b.get("sent_at", "")}


@app.get("/api/marketing/meta")
def marketing_meta():
    """Everything the audience builder needs: the Library's live topic vocabulary."""
    return {"topics": open_store().library_topics()}


@app.post("/api/marketing/preview")
def marketing_preview(f: AudienceFilter):
    """Who a filter reaches, RIGHT NOW: count + a peek — resolved live, suppression
    and emailless already excluded, deduped by email across campaigns."""
    people = open_store().audience_leads(f.model_dump())
    return {"count": len(people),
            "sample": [{"name": p["lead"].full_name, "company": p["lead"].company,
                        "email": p["email"]} for p in people[:8]]}


@app.get("/api/blasts")
def list_blasts():
    return [_blast_out(b) for b in open_store().list_blasts()]


@app.post("/api/blasts")
def create_blast(b: BlastBody):
    if not b.name.strip() or not b.subject.strip() or not b.body.strip():
        raise HTTPException(400, "name, subject and body are all required")
    bid = open_store().create_blast({"name": b.name.strip(), "subject": b.subject.strip(),
                                     "body": b.body, "audience": b.audience.model_dump()})
    return {"id": bid}


@app.get("/api/blasts/{bid}")
def get_blast(bid: str):
    b = open_store().get_blast(bid)
    if not b:
        raise HTTPException(404, "blast not found")
    return _blast_out(b)


@app.put("/api/blasts/{bid}")
def update_blast(bid: str, body: BlastBody):
    store = open_store()
    b = store.get_blast(bid)
    if not b:
        raise HTTPException(404, "blast not found")
    if b.get("status") != "draft":
        raise HTTPException(400, "only drafts can be edited")
    store.update_blast(bid, {"name": body.name.strip(), "subject": body.subject.strip(),
                             "body": body.body, "audience": body.audience.model_dump()})
    return {"ok": True}


@app.delete("/api/blasts/{bid}")
def delete_blast(bid: str):
    store = open_store()
    b = store.get_blast(bid)
    if b and b.get("status") == "sending":
        raise HTTPException(400, "can't delete a blast mid-send")
    store.delete_blast(bid)
    return {"ok": True}


class BlastTest(BaseModel):
    to: str


@app.post("/api/blasts/{bid}/test")
def test_blast(bid: str, r: BlastTest):
    """The exact rendered email (merge fields + unsubscribe footer), to YOUR inbox —
    the mandatory dress rehearsal before a real send."""
    store = open_store()
    b = store.get_blast(bid)
    if not b:
        raise HTTPException(404, "blast not found")
    to = (r.to or "").strip()
    if "@" not in to:
        raise HTTPException(400, "enter a valid email address")
    people = store.audience_leads(b.get("audience") or {})
    sample = people[0]["lead"] if people else Lead(first_name="Maria", last_name="Chen",
                                                  title="VP Operations", company="Meridian Logistics")
    msg = marketing.render_message(b, sample, to)
    msg["subject"] = f"[TEST] {msg['subject']}"
    try:
        res = postmark_send.send_batch([msg])
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    first = res[0] if res else {}
    if first.get("ErrorCode"):
        raise HTTPException(502, f"Postmark rejected it: {first.get('Message')}")
    return {"ok": True, "rendered_for": people[0]["email"] if people else "(sample lead)",
            "audience_count": len(people)}


@app.post("/api/blasts/{bid}/send")
def send_blast(bid: str):
    store = open_store()
    b = store.get_blast(bid)
    if not b:
        raise HTTPException(404, "blast not found")
    if b.get("status") == "sending":
        return {"started": False, "reason": "already sending"}
    if not postmark_send.has_key():
        raise HTTPException(400, "Postmark isn't configured — set POSTMARK_SERVER_TOKEN and MARKETING_FROM")
    th = threading.Thread(target=marketing.run_blast, args=(store, bid), daemon=True)
    th.start()
    return {"started": True}


@app.post("/api/postmark/events")
async def postmark_events(request: Request):
    """Postmark's webhook: delivery/open/click/bounce/spam/unsubscribe, one JSON
    event per call. Joined to blasts via the Metadata we attach to every send.
    Auth: shared token in the URL (?token=…) — set POSTMARK_WEBHOOK_TOKEN and use
    https://…/api/postmark/events?token=THAT in Postmark's webhook settings.
    Compliance side effects: hard bounces, spam complaints and unsubscribes go
    straight onto the global do-not-contact list — sales included."""
    want = os.environ.get("POSTMARK_WEBHOOK_TOKEN", "")
    if want and request.query_params.get("token", "") != want:
        raise HTTPException(401, "bad webhook token")
    try:
        ev = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON")
    store = open_store()
    kind = (ev.get("RecordType") or "").lower()
    email = (ev.get("Recipient") or ev.get("Email") or "").strip().lower()
    meta = ev.get("Metadata") or {}
    bid = meta.get("blast_id") or ""
    stat = {"delivery": "delivered", "open": "opened", "click": "clicked",
            "bounce": "bounced", "spamcomplaint": "spam",
            "subscriptionchange": "unsubs"}.get(kind)
    if bid and email and stat and store.mark_blast_event(bid, email, stat):
        store.inc_blast_stat(bid, stat)
    # compliance: these three mean "never again", across BOTH engines — including
    # cancelling any remaining Apollo sequence emails already scheduled for them
    if email:
        if kind == "spamcomplaint":
            store.suppress(email, "spam complaint (Postmark)")
            _stop_sequenced(store, email)
        elif kind == "subscriptionchange" and ev.get("SuppressSending"):
            store.suppress(email, "unsubscribed (Postmark)")
            _stop_sequenced(store, email)
        elif kind == "bounce" and (ev.get("Type") or "") in ("HardBounce", "BadEmailAddress"):
            store.suppress(email, "hard bounce (Postmark)")
            store.save_verify(email, "undeliverable")
            _stop_sequenced(store, email)
    return {"ok": True}


@app.get("/api/capture_token")
def capture_token_status():
    store = open_store()
    tokens = [{"id": t["_id"], "label": t.get("label", ""),
               "created_at": t.get("created_at", ""), "last_used_at": t.get("last_used_at", "")}
              for t in store.list_capture_tokens()]
    legacy = bool(store.get_setting(_CAPTURE_TOKEN_KEY))
    return {"tokens": tokens, "legacy": legacy, "exists": bool(tokens) or legacy}


class TokenCreate(BaseModel):
    label: str = ""


@app.post("/api/capture_token")
def create_capture_token(r: TokenCreate = TokenCreate()):
    """Mint a capture token for ONE person. Shown once (only its hash is stored) and
    independent of everyone else's — issuing or revoking one never disturbs the
    others, which the previous single shared token did."""
    token = "olc_" + secrets.token_urlsafe(32)   # olc = outreach linkedin capture
    tid = open_store().create_capture_token(
        (r.label or "").strip() or "unnamed", hashlib.sha256(token.encode()).hexdigest())
    return {"token": token, "id": tid}


@app.delete("/api/capture_token/{tid}")
def revoke_one_capture_token(tid: str):
    open_store().revoke_capture_token(tid)
    return {"ok": True}


@app.delete("/api/capture_token")
def revoke_legacy_capture_token():
    """Retire the old shared token once everyone has a personal one."""
    open_store().delete_setting(_CAPTURE_TOKEN_KEY)
    return {"ok": True}


@app.get("/api/linkedin/campaigns")
def linkedin_campaigns(request: Request):
    """Campaign names for the extension's target-campaign dropdown (names only)."""
    _capture_auth(request)
    return {"campaigns": open_store().campaign_names()}


# --- ICP fit for captured commenters ------------------------------------------
# A LinkedIn post's commenters are self-selected, not filtered like an Apollo pull —
# a broad post can hand us 130 software engineers for a freight campaign. This check
# compares each person against the campaign's own targeting (icp/apollo titles +
# industries/keywords) and skips CLEAR misses. Deliberately conservative: seniority
# words (director/manager/head…) don't count as fit — the DOMAIN words do (safety,
# ehs, freight…) — and people with no readable title are kept for human review.
_TITLE_STOP = {
    "of", "the", "and", "at", "for", "in", "a", "an",
    "sr", "senior", "jr", "junior", "head", "director", "manager", "managing", "lead",
    "chief", "officer", "vp", "vice", "president", "specialist", "coordinator",
    "executive", "assistant", "associate", "global", "regional", "group", "corporate",
}


def _icp_tokens(cfg: dict) -> set[str]:
    """Domain words from the campaign's targeting. Empty set = check disabled."""
    icp = cfg.get("icp") or {}
    ap = cfg.get("apollo") or {}
    words: set[str] = set()
    for t in (ap.get("titles") or icp.get("titles") or []) \
           + (ap.get("keywords") or icp.get("industries") or []):
        for w in re.split(r"[^a-z0-9]+", str(t).lower()):
            if len(w) > 1 and w not in _TITLE_STOP:
                words.add(w)
    return words


def _fits_icp(text: str, toks: set[str]) -> bool | None:
    """True = overlaps the targeting; False = readable text with ZERO overlap (clear
    miss); None = nothing readable to judge (kept — missing data isn't a mismatch)."""
    if not toks:
        return True
    words = {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) > 1}
    if not words:
        return None
    return True if words & toks else False


# --- sources: the attribution spine ------------------------------------------
@app.get("/api/sources")
def list_sources(request: Request):
    """Every place we've engaged, with what it actually produced. This is the dial:
    leads in, meetings out, per LinkedIn group / publication / community.
    Readable with a capture token too — the extension suggests known source names so
    the same group isn't logged three different ways."""
    _capture_auth(request)
    store = open_store()
    funnel = store.source_funnel()
    out = []
    for s in store.list_sources():
        f = funnel.get(s["_id"], {})
        out.append({"id": s["_id"], "name": s.get("name", ""), "type": s.get("type", ""),
                    "url": s.get("url", ""), "notes": s.get("notes", ""),
                    "created_at": s.get("created_at", ""),
                    "leads": f.get("leads", 0), "with_email": f.get("with_email", 0),
                    "sent": f.get("sent", 0), "engaged": f.get("engaged", 0),
                    "replied": f.get("replied", 0), "meetings": f.get("meetings", 0)})
    out.sort(key=lambda x: (x["meetings"], x["replied"], x["leads"]), reverse=True)
    return out


class SourceIn(BaseModel):
    name: str
    type: str = "linkedin_post"
    url: str = ""


@app.post("/api/sources")
def create_source(s: SourceIn):
    if not s.name.strip():
        raise HTTPException(400, "name is required")
    return {"id": open_store().upsert_source(s.name, s.type, s.url)}


class SourceNotes(BaseModel):
    notes: str


@app.put("/api/sources/{sid}/notes")
def update_source_notes(sid: str, r: SourceNotes):
    """The questions people asked there — our content backlog, written by buyers."""
    open_store().set_source_notes(sid, r.notes)
    return {"ok": True}


@app.delete("/api/sources/{sid}")
def delete_source(sid: str):
    open_store().delete_source(sid)
    return {"ok": True}


# --- signals: the monitoring inbox -------------------------------------------
# Platforms push; we collect. Notification email arrives via Postmark inbound,
# publisher/Google-Alert feeds are polled. Nothing here scrapes anything.
@app.post("/api/signals/inbound")
async def signals_inbound(request: Request):
    """Postmark inbound webhook. Point an inbound address (Postmark gives you one,
    or set an inbound domain) at https://…/api/signals/inbound?token=… with
    SIGNALS_WEBHOOK_TOKEN set, then forward LinkedIn / G2 / Capterra / Trustpilot /
    Google Alerts notification mail to it. Every message becomes a signal — the
    ones we can't parse keep their subject line rather than being dropped."""
    want = os.environ.get("SIGNALS_WEBHOOK_TOKEN", "")
    if want and request.query_params.get("token", "") != want:
        raise HTTPException(401, "bad webhook token")
    try:
        ev = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON")
    frm = ev.get("From") or (ev.get("FromFull") or {}).get("Email") or ""
    sig = signals.parse_email(frm, ev.get("Subject") or "",
                              ev.get("TextBody") or "", ev.get("HtmlBody") or "")
    sig["from"] = frm
    added = open_store().add_signal(sig)
    return {"ok": True, "added": added, "platform": sig["platform"], "kind": sig["kind"]}


@app.get("/api/signals")
def list_signals(status: str = ""):
    store = open_store()
    names = {s["_id"]: s.get("name", "") for s in store.list_sources()}
    out = [{"id": d["_id"], "created_at": d.get("created_at", ""),
            "channel": d.get("channel", ""), "platform": d.get("platform", ""),
            "kind": d.get("kind", ""), "person": d.get("person", ""),
            "title": d.get("title", ""), "text": d.get("text", ""),
            "url": d.get("url", ""), "status": d.get("status", "new"),
            "feed": d.get("feed", ""), "source_id": d.get("source_id", ""),
            # only present on OSHA citations — the fields that make one a lead
            "company": d.get("company", ""), "location": d.get("location", ""),
            "state": d.get("state", ""), "penalty": d.get("penalty", 0),
            "source": names.get(d.get("source_id", ""), "")}
           for d in store.list_signals(status)]
    return {"signals": out, "counts": store.signal_counts(),
            "inbound_ready": bool(os.environ.get("SIGNALS_WEBHOOK_TOKEN"))}


class SignalIn(BaseModel):
    title: str
    url: str = ""
    text: str = ""
    person: str = ""
    kind: str = "question"
    platform: str = "other"
    source_id: str = ""


@app.post("/api/signals")
def add_signal(s: SignalIn):
    """Log something you saw yourself — a question in a LinkedIn group nobody can
    notify us about. The manual path is not a fallback here, it's the main one for
    Tier 2 communities where membership is the only API."""
    if not s.title.strip():
        raise HTTPException(400, "title is required")
    d = s.model_dump()
    d["channel"] = "manual"
    d["dedupe"] = signals.dedupe_key(s.platform, s.url, s.title, s.person)
    return {"added": open_store().add_signal(d)}


class SignalAction(BaseModel):
    status: str = "engaged"


@app.post("/api/signals/{sid}/status")
def signal_status(sid: str, a: SignalAction):
    if a.status not in ("new", "engaged", "ignored"):
        raise HTTPException(400, "status must be new, engaged or ignored")
    open_store().set_signal_status(sid, a.status)
    return {"ok": True}


@app.delete("/api/signals/{sid}")
def remove_signal(sid: str):
    open_store().delete_signal(sid)
    return {"ok": True}


@app.post("/api/signals/poll")
def poll_signals():
    """Poll every feed now, rather than waiting for the half-hourly cycle."""
    store = open_store()
    res = signals.poll_all(store)
    try:
        res["citations"] = osha.poll(store)
    except Exception as e:
        res["citations_error"] = str(e)[:160]
    return res


@app.get("/api/routing")
def routing_board(request: Request):
    """Sources → campaigns: what each place has waiting, and which campaign each
    waiting lead fits. The fit is scored against what the campaign already declares
    it wants, and every route carries the terms that matched so it can be argued
    with. Leads nothing matches are reported as unrouted rather than dumped into
    whichever campaign sorted first."""
    _capture_auth(request)
    store = open_store()
    names = [c["_id"] for c in store.db.campaigns.find({}, {"_id": 1})]
    cfgs = {}
    for n in names:
        try:
            cfgs[n] = _load(n)
        except Exception:
            continue
    srcs = {s["_id"]: s for s in store.list_sources()}
    funnel = store.source_funnel()
    flows: dict[tuple, dict] = {}
    for sig in store.list_signals("new"):
        if sig.get("kind") != "citation":
            continue           # only citations are un-promoted leads today
        sid = sig.get("source_id", "")
        text = " ".join([sig.get("company", ""), sig.get("text", ""), sig.get("title", "")])
        sug = routing.suggest(text, cfgs)
        k = (sid, sug["campaign"])
        f = flows.setdefault(k, {"source_id": sid,
                                 "source": (srcs.get(sid) or {}).get("name", "Unattributed"),
                                 "campaign": sug["campaign"], "items": []})
        f["items"].append({"id": sig["_id"], "company": sig.get("company", ""),
                           "penalty": sig.get("penalty", 0), "location": sig.get("location", ""),
                           "state": sig.get("state", ""), "url": sig.get("url", ""),
                           "text": sig.get("text", ""), "why": sug["why"],
                           "alternatives": [a["campaign"] for a in sug["alternatives"]]})
    out_flows = sorted(flows.values(), key=lambda f: (-len(f["items"]), f["campaign"]))
    by_source: dict[str, int] = {}
    by_campaign: dict[str, int] = {}
    for f in out_flows:
        by_source[f["source_id"]] = by_source.get(f["source_id"], 0) + len(f["items"])
        by_campaign[f["campaign"]] = by_campaign.get(f["campaign"], 0) + len(f["items"])
    return {
        "sources": [{"id": sid, "name": (srcs.get(sid) or {}).get("name", "Unattributed"),
                     "type": (srcs.get(sid) or {}).get("type", ""),
                     "ready": n, "leads": funnel.get(sid, {}).get("leads", 0)}
                    for sid, n in sorted(by_source.items(), key=lambda kv: -kv[1])],
        "campaigns": [{"name": c, "ready": n} for c, n in sorted(by_campaign.items(), key=lambda kv: -kv[1])],
        "flows": out_flows,
        "all_campaigns": names,
    }


# --- OSHA citations → leads ---------------------------------------------------
# The one signal on this page that is a lead rather than a reading item: a named
# employer, publicly cited, with a dated and expensive problem. Resolution is split
# in two on purpose — looking a company up is free, revealing contacts costs credits,
# and nobody should email the wrong company about a worker fatality because the app
# silently took Apollo's top hit.
@app.post("/api/signals/{sid}/resolve")
def resolve_citation(sid: str):
    """Company name → Apollo organisation candidates, each with a free preview of who
    works there in safety. Costs nothing; reveals nothing."""
    store = open_store()
    sig = next((s for s in store.list_signals("") if s["_id"] == sid), None)
    if not sig:
        raise HTTPException(404, "signal not found")
    company = sig.get("company") or sig.get("title", "")
    if not company:
        raise HTTPException(400, "this signal has no company on it")
    out = []
    for org in apollo.find_org(company):
        try:
            people = apollo.preview_contacts_at_org(org["id"])
        except Exception:
            people = []
        out.append({**org, "contacts": people})
    return {"company": company, "candidates": out}


class PromoteCitation(BaseModel):
    org_id: str
    campaign: str
    limit: int = 3


@app.post("/api/signals/{sid}/promote")
def promote_citation(sid: str, r: PromoteCitation):
    """Turn a citation into leads in a campaign. Reveals contacts (credits), attaches
    the citation itself as the grounded fact the draft is written from — which is the
    whole point: this lead has a reason, unlike anything on a bought list."""
    store = open_store()
    cfg = _load(r.campaign)
    sig = next((s for s in store.list_signals("") if s["_id"] == sid), None)
    if not sig:
        raise HTTPException(404, "signal not found")
    leads, credits = apollo.contacts_at_org(r.org_id, limit=max(1, min(r.limit, 10)))
    leads = [ld for ld in leads if ld.email]        # no email, no campaign
    if not leads:
        raise HTTPException(400, "Apollo revealed no reachable contact at that company")
    src_id = sig.get("source_id") or store.upsert_source("OSHA citations", "regulator", osha.FEED_URL)
    fact = Fact(claim=sig.get("text") or sig.get("title", ""),
                source_url=sig.get("url", ""), source_type="osha",
                published=(sig.get("created_at") or "")[:10], confidence=0.95)
    research = Research(facts=[fact], summary=sig.get("text") or "")
    made = []
    for ld in leads:
        store.upsert_lead(ld, cfg["name"], ["osha-citation"], source_id=src_id)
        key = store._scoped(cfg["name"], store._base_key(ld))
        store.save_research(key, "osha-citation", research)
        made.append({"key": key, "name": ld.full_name, "title": ld.title, "email": ld.email})
    store.set_signal_status(sid, "engaged")
    return {"added": len(made), "credits": credits, "leads": made, "campaign": cfg["name"]}


class FeedIn(BaseModel):
    url: str
    name: str = ""
    keywords: list[str] = []
    source_id: str = ""


@app.get("/api/feeds")
def list_feeds():
    return [{"id": f["_id"], "url": f.get("url", ""), "name": f.get("name", ""),
             "keywords": f.get("keywords", []), "enabled": f.get("enabled", True),
             "last_poll": f.get("last_poll", ""), "last_ok": f.get("last_ok", ""),
             "last_note": f.get("last_note", ""), "ok": f.get("last_ok_flag", True)}
            for f in open_store().list_feeds()]


@app.post("/api/feeds")
def add_feed(f: FeedIn):
    if not f.url.strip().lower().startswith("http"):
        raise HTTPException(400, "url must start with http")
    store = open_store()
    fid = store.add_feed(f.url.strip(), f.name.strip(), f.keywords, f.source_id)
    try:                                    # poll immediately: a feed that's wrong
        n = signals.poll_feed(store, {"_id": fid, "url": f.url.strip(),   # should say so now
                                      "name": f.name.strip(), "keywords": f.keywords,
                                      "source_id": f.source_id})
        store.mark_feed_polled(fid, ok=True, note=f"{n} new")
        return {"id": fid, "new": n}
    except Exception as e:
        store.mark_feed_polled(fid, ok=False, note=str(e)[:160])
        raise HTTPException(400, f"Feed added but could not be read: {e}")


@app.put("/api/feeds/{fid}")
def update_feed(fid: str, f: FeedIn):
    """Retune a feed in place. Keywords are the difference between a monitor and a
    firehose, and the right ones are only obvious once you've seen what a feed
    actually carries — so they have to be editable, not set once at creation."""
    open_store().update_feed(fid, f.name.strip(), f.keywords, f.url.strip())
    return {"ok": True}


@app.delete("/api/feeds/{fid}")
def remove_feed(fid: str):
    open_store().delete_feed(fid)
    return {"ok": True}


class ClearIn(BaseModel):
    channel: str = ""        # "rss" clears topics only; blank clears the whole queue


@app.post("/api/signals/clear")
def clear_signals(c: ClearIn):
    """Dismiss the queue in one go. Retuning a feed's keywords doesn't retroactively
    remove what the old settings let through, so there has to be a way to wipe the
    slate rather than clicking 111 checkmarks."""
    return {"cleared": open_store().clear_signals(c.channel)}


@app.post("/api/feeds/{fid}/toggle")
def toggle_feed(fid: str, a: SignalAction):
    open_store().set_feed_enabled(fid, a.status == "on")
    return {"ok": True}


# --- backlog: what the buyers asked, which is what we write next --------------
class BacklogIn(BaseModel):
    question: str
    source_id: str = ""
    signal_id: str = ""
    url: str = ""


@app.get("/api/backlog")
def list_backlog():
    store = open_store()
    names = {s["_id"]: s.get("name", "") for s in store.list_sources()}
    return [{"id": b["_id"], "question": b.get("question", ""), "url": b.get("url", ""),
             "status": b.get("status", "idea"), "created_at": b.get("created_at", ""),
             "source_id": b.get("source_id", ""),
             "source": names.get(b.get("source_id", ""), "")}
            for b in store.list_backlog()]


@app.post("/api/backlog")
def add_backlog(b: BacklogIn):
    if not b.question.strip():
        raise HTTPException(400, "question is required")
    return {"id": open_store().add_backlog(b.question.strip(), b.source_id, b.signal_id, b.url)}


@app.post("/api/backlog/{bid}/status")
def backlog_status(bid: str, a: SignalAction):
    open_store().set_backlog_status(bid, a.status)
    return {"ok": True}


@app.delete("/api/backlog/{bid}")
def remove_backlog(bid: str):
    open_store().delete_backlog(bid)
    return {"ok": True}


class Commenter(BaseModel):
    name: str = ""
    profile_url: str = ""
    headline: str = ""


class LinkedInCapture(BaseModel):
    campaign: str
    post_url: str = ""
    commenters: list[Commenter] = []
    skip_filter: bool = False   # true = capture everyone; the targeting filter is bypassed
    source_name: str = ""       # the group/community/publication this thread lives in
    source_type: str = "linkedin_post"


@app.post("/api/linkedin/capture")
def linkedin_capture(r: LinkedInCapture, request: Request):
    """Ingest commenters captured from a LinkedIn post into a campaign.

    Per commenter: dedup by profile URL (batch + already-in-campaign — a repeat
    capture never re-spends credits), enrich via Apollo bulk_match keyed on the
    profile URL (~1 credit per match), honor the do-not-contact list, then upsert
    as a normal 'new' lead (source linkedin_comment) for the standard pipeline —
    nothing is drafted or sent without the usual review."""
    _capture_auth(request)
    cfg = _load(r.campaign)
    store = open_store()
    if len(r.commenters) > 200:
        raise HTTPException(400, "too many commenters in one capture (max 200) — send in batches")

    # dedup: within this batch, and against everyone already in the campaign
    existing = {apollo.normalize_linkedin_url(l.linkedin_url)
                for l in store.leads(cfg["name"]) if l.linkedin_url}
    fresh, seen, duplicates = [], set(), 0
    for c in r.commenters:
        url = apollo.normalize_linkedin_url(c.profile_url)
        if not url or "/in/" not in url:     # no profile link = nothing to match on
            continue
        if url in seen or url in existing:
            duplicates += 1
            continue
        seen.add(url)
        fresh.append({"name": c.name.strip(), "profile_url": c.profile_url.strip(),
                      "headline": c.headline.strip()})

    # ICP fit, pass 1 — the headline, BEFORE enrichment: a clear miss ("Software
    # Engineer" into a freight campaign) is skipped without spending a credit.
    # Every skip is REPORTED back (name + headline), never silent — a warm lead
    # wrongly skipped can be rescued by re-sending with skip_filter on.
    toks = set() if r.skip_filter else _icp_tokens(cfg)
    off_icp = 0
    skipped: list[dict] = []
    if toks:
        kept = []
        for c in fresh:
            if _fits_icp(c["headline"], toks) is False:
                off_icp += 1
                if len(skipped) < 40:   # profile_url included so the panel can one-click rescue
                    skipped.append({"name": c["name"], "profile_url": c["profile_url"],
                                    "headline": c["headline"][:80]})
            else:
                kept.append(c)
        fresh = kept
    if not fresh:
        return {"received": len(r.commenters), "added": 0, "with_email": 0, "no_email": 0,
                "duplicates": duplicates, "off_icp": off_icp, "skipped": skipped,
                "suppressed": 0, "credits_used": 0, "counts": store.counts(cfg["name"])}

    # enrich from Apollo's database (LinkedIn contributed only the pointer)
    credits = 0
    if apollo.has_key():
        try:
            leads, credits = apollo.match_commenters(fresh)
        except Exception as e:
            raise HTTPException(502, f"Apollo match failed: {e}")
    else:   # no key: keep captured skeletons; downstream enrichment may fill emails
        leads = []
        for c in fresh:
            title, company = apollo.parse_headline(c["headline"])
            first, _, last = c["name"].partition(" ")
            leads.append(Lead(first_name=first, last_name=last, title=title,
                              company=company, linkedin_url=c["profile_url"]))

    topics = tagging.topics_of(cfg)
    # attribute this capture: named source if the extension sent one, else the post URL
    src_id = store.upsert_source(r.source_name or r.post_url or "LinkedIn",
                                 r.source_type or "linkedin_post", r.post_url)
    added = with_email = suppressed = 0
    for c, lead in zip(fresh, leads):
        if lead.email and store.is_suppressed(lead.email):
            suppressed += 1
            continue
        # ICP fit, pass 2 — Apollo's verified title (fresher than the headline). Only
        # people whose headline was unreadable reach here unjudged; a clear miss on
        # BOTH title and headline is skipped rather than added to the campaign.
        if toks and _fits_icp(f"{lead.title} {c['headline']}", toks) is False:
            off_icp += 1
            if len(skipped) < 40:
                skipped.append({"name": c["name"], "profile_url": c["profile_url"],
                                "headline": (lead.title or c["headline"])[:80]})
            continue
        lead.source = "linkedin_comment"
        lead.raw = {**(lead.raw or {}),
                    "linkedin_capture": {"post_url": r.post_url, "headline": c["headline"]}}
        store.upsert_lead(lead, cfg["name"], topics, source_id=src_id)
        added += 1
        if lead.email:
            with_email += 1
    return {"received": len(r.commenters), "added": added, "with_email": with_email,
            "no_email": added - with_email, "duplicates": duplicates,
            "off_icp": off_icp, "skipped": skipped, "suppressed": suppressed,
            "credits_used": credits, "counts": store.counts(cfg["name"])}


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
    src_id = store.upsert_source("Apollo search", "apollo")   # comparable to every other source
    skipped = 0
    no_email = 0
    for lead in leads_in:
        lead.source = "apollo"
        if lead.email and store.is_suppressed(lead.email):  # compliance: never re-import
            skipped += 1
            continue
        if not lead.company_domain and lead.company:  # enrich missing domains (free, guarded)
            d = enrich.find_domain(lead.company)
            if d:
                lead.company_domain = d
        if not lead.email:  # Apollo couldn't reveal an email — an unemailable lead only clutters, so skip it
            no_email += 1
            continue
        store.upsert_lead(lead, cfg["name"], topics, source_id=src_id)
    return {"pulled": len(leads_in) - skipped - no_email, "suppressed": skipped, "no_email": no_email,
            "credits_used": credits, "counts": store.counts(cfg["name"])}


class RunReq(BaseModel):
    campaign: str
    send: bool = False
    limit: int | None = None   # process at most N leads per run (None = all); guards cost


def _do_run(name: str, send: bool, limit: int | None):
    try:
        cfg = _load(name)
        store = open_store()
        def _prog(sent, done, total):   # live progress for the UI's send/draft bar
            r = _runs.get(name)
            if r is not None:
                r["progress"] = {"sent": sent, "done": done, "total": total}
        pipeline.run(store, cfg, dry_run=not send, limit=limit, require_review=True, on_progress=_prog)
        _runs[name] = {"running": False, "error": None, "summary": store.counts(cfg["name"])}
    except Exception as e:
        _runs[name] = {"running": False, "error": str(e), "summary": {}}


# A run should never legitimately take this long; past it a still-'running' flag is
# treated as orphaned so a campaign can't get permanently locked out of sending.
_RUN_STALE_SECS = 900  # 15 min


def _run_in_progress(campaign: str) -> bool:
    """True only when a run is genuinely still executing. A 'running' flag whose
    worker thread has died — or that has been stuck past _RUN_STALE_SECS — is stale
    and ignored, so an orphaned flag (e.g. a thread killed mid-run) never blocks all
    future sends. This is the fix for a Send that silently no-ops with 'already
    running' forever."""
    st = _runs.get(campaign) or {}
    if not st.get("running"):
        return False
    th = _run_threads.get(campaign)
    if th is not None and not th.is_alive():
        return False  # worker died without clearing the flag
    if time.time() - st.get("started_at", 0) > _RUN_STALE_SECS:
        return False  # stuck far too long — treat as orphaned
    return True


@app.post("/api/run")
def run(req: RunReq):
    if _run_in_progress(req.campaign):
        return {"started": False, "reason": "already running"}
    th = threading.Thread(target=_do_run, args=(req.campaign, req.send, req.limit), daemon=True)
    _runs[req.campaign] = {"running": True, "error": None, "summary": {}, "started_at": time.time(),
                           "progress": {"sent": 0, "done": 0, "total": 0}}
    _run_threads[req.campaign] = th
    th.start()
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
