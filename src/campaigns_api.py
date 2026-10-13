"""The campaign pages (KnowCRM phase 2, item 16): the list of campaigns with how each is
doing, and inside a campaign its sequence (every step with what it produced) and its
activity (every email sent).

Delivered steps come from Apollo through the reply sync (src/reply_sync.py, the
`messages` collection); sends, replies and meetings from our own records. Scope is the
campaign's: admins see every campaign, sales users their own, and anything else answers
404 like a campaign that doesn't exist.
"""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, HTTPException

from . import access
from .crm_api import _names
from .store import open_store

router = APIRouter()
ACTIVITY_MAX = 200
# Activity filters: what a delivered or attempted step turned into.
STATUSES = ("delivered", "replied", "bounced", "failed", "scheduled")


def _visible(store, u: dict) -> list[str]:
    owners = store.campaign_owners()
    return [n for n in store.campaign_names() if access.campaign_visible(u, owners.get(n, ""))]


def _campaign_or_404(store, u: dict, name: str) -> dict:
    cfg = store.get_campaign(name) if name else None
    if cfg is None or not access.campaign_visible(u, store.campaign_owner(name)):
        raise HTTPException(404, f"campaign '{name}' not found")
    return cfg


def _by_campaign(col, names: set[str]) -> dict[str, list[dict]]:
    """Rows of a collection keyed `campaign::email`, grouped by campaign."""
    out: dict[str, list[dict]] = {}
    for d in col.find({}, {"label": 1}):
        camp = str(d["_id"]).split("::", 1)[0]
        if camp in names:
            out.setdefault(camp, []).append(d)
    return out


def _sending(cfg: dict) -> dict:
    s = cfg.get("sending") or {}
    seq = (s.get("sequence_id") or "").strip()
    boxes = s.get("mailbox_ids") or ([s["mailbox_id"]] if s.get("mailbox_id") else [])
    return {"sequence_id": seq if seq and not seq.startswith("<") else "", "mailboxes": len(boxes),
            "wired": bool(seq and not seq.startswith("<") and boxes)}


@router.get("/api/campaigns/summary")
def campaigns_summary():
    """Every campaign you can see, with how far it has got: leads, waiting for review,
    sent, replies, interested and meetings."""
    store = open_store()
    u = access.require_user()
    names = _visible(store, u)
    want = set(names)
    status: dict[str, Counter] = {n: Counter() for n in names}
    for d in store.db.leads.aggregate([{"$match": {"campaign": {"$in": names}}},
                                       {"$group": {"_id": {"c": "$campaign", "s": "$status"}, "n": {"$sum": 1}}}]):
        status[d["_id"]["c"]][d["_id"]["s"]] = d["n"]
    sent = _by_campaign(store.db.sends, want)
    replies = _by_campaign(store.db.replies, want)
    meetings = _by_campaign(store.db.meetings, want)
    owners, people = store.campaign_owners(), _names(store)
    owner_emails = {d["_id"]: d.get("owner_email") or "" for d in store.db.campaigns.find({}, {"owner_email": 1})}
    out = []
    for n in names:
        cfg = store.get_campaign(n) or {}
        st = status[n]
        rs = replies.get(n, [])
        owner = owners.get(n, "")
        out.append({"name": n, "product": (cfg.get("offer") or {}).get("product", ""),
                    "owner": owner,
                    # their name, else the address they were given the campaign under
                    "owner_name": (people.get(owner) or owner_emails.get(n, "") or "someone") if owner else "",
                    "steps": len(((cfg.get("sequence") or {}).get("steps")) or []) or 1,
                    "leads": sum(st.values()), "to_review": st.get("queued", 0),
                    "sent": len(sent.get(n, [])), "replies": len(rs),
                    "interested": sum(1 for r in rs if r.get("label") == "interested"),
                    "meetings": len(meetings.get(n, [])), "sending": _sending(cfg)})
    return {"campaigns": out}


@router.get("/api/campaign/sequence")
def campaign_sequence(campaign: str):
    """The campaign's email steps (day, subject, template) and what each produced:
    delivered, replied (by Apollo's reply class), bounced, failed, still scheduled."""
    store = open_store()
    u = access.require_user()
    cfg = _campaign_or_404(store, u, campaign)
    seq = cfg.get("sequence") or {}
    steps = seq.get("steps") or [{"wait_days": 0, "subject": "", "template": ""}]
    stats: dict[int, Counter] = {}
    for m in store.db.messages.find({"campaign": campaign}, {"step": 1, "status": 1, "delivered_at": 1,
                                                              "replied": 1, "reply_class": 1, "bounce": 1, "failed": 1}):
        c = stats.setdefault(int(m.get("step") or 0), Counter())
        if m.get("bounce"):
            c["bounced"] += 1
        elif m.get("failed"):
            c["failed"] += 1
        elif m.get("delivered_at"):
            c["delivered"] += 1
        else:
            c["scheduled"] += 1
        if m.get("replied"):
            c["replied"] += 1
            c["class:" + (m.get("reply_class") or "unclassified")] += 1
    out, day = [], 1
    for i, s in enumerate(steps, start=1):
        if i > 1:
            day += max(1, int(s.get("wait_days") or 0))
        c = stats.get(i, Counter())
        out.append({"step": i, "day": day, "wait_days": 0 if i == 1 else max(1, int(s.get("wait_days") or 0)),
                    "subject": s.get("subject", ""), "template": s.get("template", ""),
                    "written_per_lead": i == 1 and seq.get("use_ai", True) is not False,
                    "delivered": c["delivered"], "replied": c["replied"], "bounced": c["bounced"],
                    "failed": c["failed"], "scheduled": c["scheduled"],
                    "reply_classes": {k[6:]: v for k, v in c.items() if k.startswith("class:")}})
    extra = sorted(k for k in stats if k > len(steps))           # Apollo steps the plan no longer lists
    return {"campaign": campaign, "steps": out, "untracked_steps": extra, "sending": _sending(cfg),
            "synced": bool(stats), "leads": store.db.leads.count_documents({"campaign": campaign})}


@router.get("/api/campaign/activity")
def campaign_activity(campaign: str, step: int = 0, status: str = "", offset: int = 0, limit: int = 100):
    """Every email the campaign's sequence sent or tried to, newest first, with who it
    went to and what came of it. step= and status= narrow it."""
    store = open_store()
    u = access.require_user()
    _campaign_or_404(store, u, campaign)
    if status and status not in STATUSES:
        raise HTTPException(400, f"status is one of {', '.join(STATUSES)}")
    if offset < 0 or not 1 <= limit <= ACTIVITY_MAX:
        raise HTTPException(400, f"offset must be 0 or more and limit 1 to {ACTIVITY_MAX}")
    q: dict = {"campaign": campaign}
    if step:
        q["step"] = step
    if status == "delivered":
        q.update({"delivered_at": {"$nin": ["", None]}, "bounce": {"$ne": True}})
    elif status == "replied":
        q["replied"] = True
    elif status == "bounced":
        q["bounce"] = True
    elif status == "failed":
        q.update({"failed": True, "bounce": {"$ne": True}})
    elif status == "scheduled":
        q.update({"delivered_at": {"$in": ["", None]}, "bounce": {"$ne": True}, "failed": {"$ne": True}})
    total = store.db.messages.count_documents(q)
    rows = list(store.db.messages.find(q).sort([("delivered_at", -1), ("_id", 1)]).skip(offset).limit(limit))
    leads = {d["_id"]: d for d in store.db.leads.find(
        {"_id": {"$in": list({r.get("enrollment") for r in rows})}},
        {"person_id": 1, "lead.first_name": 1, "lead.last_name": 1, "lead.email": 1, "lead.company": 1, "lead.title": 1})}
    out = []
    for r in rows:
        d = leads.get(r.get("enrollment")) or {}
        lead = d.get("lead") or {}
        out.append({"id": str(r["_id"]), "step": r.get("step"), "delivered_at": r.get("delivered_at") or "",
                    "outcome": ("bounced" if r.get("bounce") else "failed" if r.get("failed")
                                else "delivered" if r.get("delivered_at") else "scheduled"),
                    "replied": bool(r.get("replied")), "reply_class": r.get("reply_class") or "",
                    "person_id": d.get("person_id", ""),
                    "name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                    "email": lead.get("email", ""), "company": lead.get("company", ""), "title": lead.get("title", "")})
    return {"total": total, "offset": offset, "items": out}
