"""The All leads and Companies pages: people and companies, notes and a timeline.

Who sees what (docs/knowcrm-requirements-audit.md §3.2): admins see everyone; sales
users see the people they own, and the companies they own or have people at. Anything
outside your scope answers 404, like something that doesn't exist. Marketing has no
access (every route here is SALES in access.POLICY).

A lead's stage is the one someone set by hand, else one derived from what happened
(sent, replied, meeting, opted out), marked `stage_auto` so the page can say so.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import access, crm, enroll, tagging, work
from .models import Lead
from .store import open_store

router = APIRouter()

_RAW_KEYS = ("headline", "seniority", "departments", "functions", "city", "state", "country", "time_zone")


# --- scope ------------------------------------------------------------------------
def _me() -> dict:
    return access.require_user()


def _people_filter(u: dict) -> dict:
    return {} if access.is_admin(u) else {"owner": u.get("id") or "\0"}


def _person_or_404(store, pid: str, u: dict) -> dict:
    d = store.db.people.find_one({"_id": pid, **_people_filter(u)})
    if not d:
        raise HTTPException(404, "lead not found")
    return d


def _company_visible(store, u: dict, c: dict) -> bool:
    if access.is_admin(u):
        return True
    uid = u.get("id")
    return bool(uid) and (c.get("owner") == uid
                          or store.db.people.find_one({"company_id": c["_id"], "owner": uid}, {"_id": 1}) is not None)


def _company_or_404(store, cid: str, u: dict) -> dict:
    c = store.db.companies.find_one({"_id": cid})
    if not c or not _company_visible(store, u, c):
        raise HTTPException(404, "company not found")
    return c


def _campaign_visible(store, u: dict, name: str) -> bool:
    return store.campaign_exists(name) and access.campaign_visible(u, store.campaign_owner(name))


def _actor(u: dict) -> dict:
    return {"id": u.get("id", ""), "email": u.get("email", ""), "label": u.get("name") or u.get("email", "")}


def _names(store) -> dict:
    return {d["_id"]: d.get("name") or (d.get("email") or "").split("@")[0] for d in store.db.users.find({}, {"name": 1, "email": 1})}


# --- facts: what happened to each enrollment ----------------------------------------
class _Facts:
    """Sends, replies, meetings and suppression, read once per request; and the calls,
    LinkedIn touches and emails logged on `person_ids` (None: everyone's, (): nobody's)."""

    def __init__(self, store, enrollment_keys: list[str] | None, person_ids: list[str] | None | tuple = ()):
        q = {"_id": {"$in": enrollment_keys}} if enrollment_keys is not None else {}
        self.sent = {d["_id"]: d.get("created_at") for d in store.db.sends.find(q, {"created_at": 1})}
        self.replies = {d["_id"]: d for d in store.db.replies.find(q)}
        self.meetings = {d["_id"]: d.get("at") for d in store.db.meetings.find(q)}
        vals = [str(d.get("value") or d.get("_id") or "").lower() for d in store.db.suppression.find({}, {"value": 1})]
        self.dnc_emails = {v for v in vals if "@" in v}
        self.dnc_domains = {v.lstrip("@") for v in vals if "@" not in v}
        self.touched: set = set()        # someone logged a call, LinkedIn touch or email
        self.call_meeting: set = set()   # a call that booked a meeting
        if person_ids != ():
            tq: dict = {"type": {"$in": list(work.TOUCH_TYPES.values())}}
            if person_ids is not None:
                tq["person_id"] = {"$in": list(person_ids)}
            for a in store.db.activities.find(tq, {"person_id": 1, "meta.outcome": 1}):
                self.touched.add(a.get("person_id"))
                if (a.get("meta") or {}).get("outcome") == "meeting":
                    self.call_meeting.add(a.get("person_id"))

    def suppressed(self, email: str) -> bool:
        e = (email or "").lower()
        return bool(e) and (e in self.dnc_emails or e.rsplit("@", 1)[-1] in self.dnc_domains)

    def lead_stage(self, person: dict, enrollments: list[dict]) -> str:
        keys = [e["_id"] for e in enrollments]
        return crm.derived_lead_stage({
            "suppressed": self.suppressed(person.get("email", "")) or any(e.get("status") == "suppressed" for e in enrollments),
            "meeting": any(k in self.meetings for k in keys) or person.get("_id") in self.call_meeting,
            "labels": [self.replies[k].get("label") for k in keys if k in self.replies and self.replies[k].get("label")],
            "replied": any(k in self.replies for k in keys),
            "sent": any(k in self.sent for k in keys) or person.get("_id") in self.touched,
        })


def _enrollments(store, person_ids: list[str] | None) -> dict[str, list[dict]]:
    q = {"person_id": {"$in": person_ids}} if person_ids is not None else {"person_id": {"$exists": True}}
    out: dict[str, list[dict]] = {}
    for d in store.db.leads.find(q, {"person_id": 1, "campaign": 1, "status": 1, "topics": 1, "pulled_at": 1}):
        out.setdefault(d["person_id"], []).append(d)
    return out


def _name(p: dict) -> str:
    return f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()


def _iso(v) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else (v or "")


# --- meta -------------------------------------------------------------------------
@router.get("/api/crm/meta")
def crm_meta():
    return {"lead_stages": crm.LEAD_STAGES, "lead_open": crm.LEAD_OPEN,
            "company_stages": crm.COMPANY_STAGES, "company_open": crm.COMPANY_OPEN,
            "interests": crm.INTERESTS, "function_labels": tagging.FUNCTION_LABELS}


# --- people -----------------------------------------------------------------------
@router.get("/api/people")
def people_list():
    """Every lead you can see, one row per person, with what the list filters on."""
    store = open_store()
    u = _me()
    people = list(store.db.people.find(_people_filter(u), {
        "first_name": 1, "last_name": 1, "title": 1, "company": 1, "company_id": 1, "email": 1,
        "owner": 1, "stage": 1, "source": 1, "created_at": 1, "interests": 1}))
    ids = [p["_id"] for p in people]
    enr = _enrollments(store, None if access.is_admin(u) else ids)
    facts = _Facts(store, None if access.is_admin(u) else [e["_id"] for es in enr.values() for e in es],
                   None if access.is_admin(u) else ids)
    engaged = store.engagement_by_email()
    names = _names(store)
    camp_topics: dict[str, list] = {}

    def topics_of(row: dict) -> list:
        """A row's own topics, else its campaign's (as the Library always did)."""
        if row.get("topics"):
            return row["topics"]
        camp = row.get("campaign", "")
        if camp not in camp_topics:
            try:
                camp_topics[camp] = tagging.topics_of(store.get_campaign(camp) or {})
            except Exception:  # noqa: BLE001
                camp_topics[camp] = []
        return camp_topics[camp]

    out = []
    for p in people:
        es = enr.get(p["_id"], [])
        auto = facts.lead_stage(p, es)
        e = engaged.get((p.get("email") or "").lower(), {})
        topics = sorted({t for x in es for t in topics_of(x)})
        out.append({
            "id": p["_id"], "name": _name(p), "title": p.get("title", ""), "company": p.get("company", ""),
            "company_id": p.get("company_id", ""), "email": p.get("email", ""),
            "owner": p.get("owner", ""), "owner_name": names.get(p.get("owner", ""), ""),
            "stage": p.get("stage") or auto, "stage_auto": not p.get("stage"),
            "function": tagging.function_of(p.get("title", "")), "topics": topics,
            "campaigns": [{"campaign": x.get("campaign", ""), "status": x.get("status", "")} for x in es],
            "engagement": "clicked" if e.get("clicked") else ("opened" if e.get("opened") else ""),
            "source": (p.get("source") or {}).get("type", ""), "created_at": p.get("created_at", ""),
            "interests": p.get("interests") or []})
    return {"people": out, "function_labels": tagging.FUNCTION_LABELS}


def _apollo_details(store, enrollments: list[dict]) -> dict:
    """The Apollo person record from their most recent lead row: the parts worth reading."""
    if not enrollments:
        return {}
    latest = sorted(enrollments, key=lambda e: _iso(e.get("pulled_at")))[-1]
    d = store.db.leads.find_one({"_id": latest["_id"]}, {"lead.raw": 1}) or {}
    raw = ((d.get("lead") or {}).get("raw")) or {}
    out = {k: raw[k] for k in _RAW_KEYS if raw.get(k)}
    hist = []
    for h in (raw.get("employment_history") or [])[:6]:
        if isinstance(h, dict):
            hist.append({"title": h.get("title") or "", "company": h.get("organization_name") or "",
                         "start": h.get("start_date") or "", "end": h.get("end_date") or "",
                         "current": bool(h.get("current"))})
    if hist:
        out["employment_history"] = hist
    return out


def _timeline(store, person_ids: list[str], company_id: str, enrollments: list[dict], facts: _Facts,
              who: dict[str, str] | None = None) -> list[dict]:
    """Notes, stage and owner changes, and what happened in each campaign (sent, replied,
    meeting), newest first. Entries with no known date go last."""
    q: dict = {"person_id": {"$in": person_ids}}
    if company_id:
        q = {"$or": [q, {"company_id": company_id, "person_id": ""}]}
    out = []
    for a in store.db.activities.find(q):
        out.append({"id": str(a["_id"]), "type": a.get("type", ""), "at": a.get("at", ""), "body": a.get("body", ""),
                    "by": (a.get("by") or {}).get("label", ""), "by_id": (a.get("by") or {}).get("id", ""),
                    "person_id": a.get("person_id", ""), "campaign": a.get("campaign", ""),
                    "pinned": bool(a.get("pinned")), "meta": a.get("meta") or {}})
    # every step Apollo delivered (src/reply_sync.py); before a sync has seen a lead's
    # messages, just the first email from the send record
    msgs: dict[str, list[dict]] = {}
    for m in store.db.messages.find({"enrollment": {"$in": [e["_id"] for e in enrollments]}},
                                    {"enrollment": 1, "step": 1, "status": 1, "delivered_at": 1, "bounce": 1}):
        msgs.setdefault(m["enrollment"], []).append(m)
    for e in enrollments:
        k, camp, pid = e["_id"], e.get("campaign", ""), e.get("person_id", "")
        delivered = [m for m in msgs.get(k, []) if m.get("delivered_at")]
        for m in delivered:
            step = f"Email {m['step']}" if m.get("step") else "Email"
            out.append({"id": f"msg:{m['_id']}", "type": "email_sent", "at": m["delivered_at"], "campaign": camp,
                        "person_id": pid, "body": f"{step} delivered · {camp}" + (" · bounced" if m.get("bounce") else ""),
                        "by": "", "derived": True})
        if not delivered and k in facts.sent:
            out.append({"id": f"sent:{k}", "type": "email_sent", "at": _iso(facts.sent[k]), "campaign": camp,
                        "person_id": pid, "body": f"First email sent · {camp}", "by": "", "derived": True})
        if k in facts.replies:
            r = facts.replies[k]
            out.append({"id": f"reply:{k}", "type": "reply", "at": r.get("at", ""), "campaign": camp, "person_id": pid,
                        "body": f"Replied · {camp}", "meta": {"label": r.get("label", "")}, "by": "", "derived": True})
        if k in facts.meetings:
            out.append({"id": f"meeting:{k}", "type": "meeting", "at": _iso(facts.meetings[k]), "campaign": camp,
                        "person_id": pid, "body": f"Meeting booked · {camp}", "by": "", "derived": True})
    if who:
        for x in out:
            x["who"] = who.get(x.get("person_id", ""), "")
    dated = sorted([x for x in out if x.get("at")], key=lambda x: (x["at"], x["id"]), reverse=True)
    return dated + [x for x in out if not x.get("at")]


@router.get("/api/people/{pid}")
def person_detail(pid: str):
    store = open_store()
    u = _me()
    p = _person_or_404(store, pid, u)
    es = _enrollments(store, [pid]).get(pid, [])
    facts = _Facts(store, [e["_id"] for e in es], [pid])
    auto = facts.lead_stage(p, es)
    names = _names(store)
    company = None
    if p.get("company_id"):
        c = store.db.companies.find_one({"_id": p["company_id"]}) or {}
        if c:
            company = {k: c.get(k) for k in ("name", "domain", "industry", "employees", "city", "state", "country",
                                              "phone", "linkedin_url", "website_url")}
            company["id"] = c["_id"]
    enrollments = []
    for e in sorted(es, key=lambda e: _iso(e.get("pulled_at")), reverse=True):
        k = e["_id"]
        r = facts.replies.get(k) or {}
        enrollments.append({"key": k, "campaign": e.get("campaign", ""), "status": e.get("status", ""),
                            "added": _iso(e.get("pulled_at")), "sent": _iso(facts.sent.get(k)) if k in facts.sent else "",
                            "replied": k in facts.replies, "reply_label": r.get("label", ""),
                            "meeting": k in facts.meetings,
                            "yours": _campaign_visible(store, u, e.get("campaign", ""))})
    return {
        "id": p["_id"], "name": _name(p), "first_name": p.get("first_name", ""), "last_name": p.get("last_name", ""),
        "title": p.get("title", ""), "email": p.get("email", ""), "emails": p.get("emails") or [],
        "phones": p.get("phones") or [], "linkedin_url": p.get("linkedin_url", ""),
        "company_name": p.get("company", ""), "company": company,
        "owner": p.get("owner", ""), "owner_name": names.get(p.get("owner", ""), ""),
        "stage": p.get("stage") or auto, "stage_auto": not p.get("stage"), "stage_derived": auto,
        "interests": p.get("interests") or [], "not_fit_reason": p.get("not_fit_reason", ""),
        "source": p.get("source") or {}, "sourced_by": p.get("sourced_by") or {},
        "created_at": p.get("created_at", ""), "suppressed": facts.suppressed(p.get("email", "")),
        "function": tagging.function_of(p.get("title", "")),
        "apollo": _apollo_details(store, es), "enrollments": enrollments,
        "tasks": _open_tasks(store, u, pid, names),
        "timeline": _timeline(store, [pid], "", es, facts)}


def _open_tasks(store, u: dict, pid: str, names: dict) -> list[dict]:
    """The lead's open tasks: yours, or everyone's for an admin."""
    q: dict = {"person_id": pid, "status": "open"}
    if not access.is_admin(u):
        q["owner"] = u.get("id") or "\0"
    return [{"id": str(t["_id"]), "kind": t.get("kind", "todo"), "title": t.get("title", ""), "due": t.get("due", ""),
             "status": t.get("status", "open"), "person_id": pid,
             "owner": t.get("owner", ""), "owner_name": names.get(t.get("owner", ""), "")}
            for t in store.db.tasks.find(q).sort([("due", 1), ("_id", 1)]).limit(50)]


class PersonCreate(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    title: str = ""
    company: str = ""
    company_domain: str = ""
    phone: str = ""
    linkedin_url: str = ""


def _clip(s: str, n: int) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


@router.post("/api/people")
def person_create(r: PersonCreate):
    """Add a lead by hand. Refused when the person already exists (said plainly, with
    their owner's name, but nothing more if they aren't yours)."""
    store = open_store()
    u = _me()
    email = crm.norm_email(r.email)
    if r.email.strip() and not email:
        raise HTTPException(400, "that email address doesn't look right")
    li = crm.norm_linkedin(r.linkedin_url)
    if r.linkedin_url.strip() and not li:
        raise HTTPException(400, "the LinkedIn link should look like linkedin.com/in/…")
    lead = {"first_name": _clip(r.first_name, 80), "last_name": _clip(r.last_name, 80), "email": email,
            "title": _clip(r.title, 160), "company": _clip(r.company, 160),
            "company_domain": crm.norm_domain(r.company_domain), "linkedin_url": li, "source": "manual", "raw": {}}
    if not (lead["first_name"] or lead["last_name"]):
        raise HTTPException(400, "a name is needed")
    ids = crm.identity(lead)
    if not (ids["email"] or ids["linkedin"]):
        raise HTTPException(400, "add an email or a LinkedIn link, so this person can be told apart")
    existing = store.find_person(ids)
    if existing is not None:
        if access.is_admin(u) or existing.get("owner") == u.get("id"):
            raise HTTPException(409, {"message": "This lead already exists.", "id": existing["_id"]})
        owner = _names(store).get(existing.get("owner", ""), "") or "an admin"
        raise HTTPException(409, {"message": f"This lead already exists and belongs to {owner}."})
    by = _actor(u)
    pid, cid, created = store.upsert_person(lead, u.get("id", ""), u.get("email", ""), by, crm.now_iso())
    if not created:
        raise HTTPException(409, {"message": "This lead was just added by someone else."})
    phone = _clip(r.phone, 40)
    if phone:
        store.db.people.update_one({"_id": pid}, {"$set": {"phones": [phone]}})
    store.add_activity(pid, cid, "created", by, "Added by hand")
    return {"id": pid}


class PersonPatch(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    phones: list[str] | None = None
    linkedin_url: str | None = None
    stage: str | None = None             # "" = back to the derived stage
    interests: list[str] | None = None
    not_fit_reason: str | None = None
    owner: str | None = None             # admins only


def _owner_check(store, owner: str) -> dict:
    if not owner:
        return {}
    o = store.get_user(owner)
    if not o or not o.get("active", True) or o.get("role") not in ("sales", "admin"):
        raise HTTPException(400, "the owner must be an active sales person or admin")
    return o


@router.patch("/api/people/{pid}")
def person_update(pid: str, r: PersonPatch):
    store = open_store()
    u = _me()
    p = _person_or_404(store, pid, u)
    by = _actor(u)
    sets: dict = {}
    events: list[tuple[str, str, dict]] = []
    for f, n in (("first_name", 80), ("last_name", 80), ("title", 160)):
        v = getattr(r, f)
        if v is not None and _clip(v, n) != p.get(f, ""):
            sets[f] = _clip(v, n)
    if r.phones is not None:
        phones = [x for x in (_clip(v, 40) for v in r.phones) if x][:5]
        if phones != (p.get("phones") or []):
            sets["phones"] = phones
    if r.linkedin_url is not None:
        li = crm.norm_linkedin(r.linkedin_url)
        if r.linkedin_url.strip() and not li:
            raise HTTPException(400, "the LinkedIn link should look like linkedin.com/in/…")
        if li != p.get("linkedin_url", ""):
            sets["linkedin_url"] = li
    if r.interests is not None:
        bad = [i for i in r.interests if i not in crm.ALL_INTERESTS]
        if bad:
            raise HTTPException(400, f"not an interest on the list: {bad[0]}")
        ints = sorted(set(r.interests), key=crm.ALL_INTERESTS.index)
        if ints != (p.get("interests") or []):
            sets["interests"] = ints
    if r.not_fit_reason is not None and _clip(r.not_fit_reason, 300) != p.get("not_fit_reason", ""):
        sets["not_fit_reason"] = _clip(r.not_fit_reason, 300)
    if r.stage is not None and r.stage != (p.get("stage") or ""):
        if r.stage and r.stage not in crm.LEAD_STAGES:
            raise HTTPException(400, "not a lead stage")
        sets["stage"] = r.stage
        events.append(("stage_change", f"Stage: {p.get('stage') or 'automatic'} → {r.stage or 'automatic'}",
                       {"from": p.get("stage") or "", "to": r.stage}))
    if r.owner is not None and r.owner != (p.get("owner") or ""):
        if not access.is_admin(u):
            raise HTTPException(403, "only an admin can change a lead's owner")
        o = _owner_check(store, r.owner)
        sets["owner"], sets["owner_email"] = r.owner, o.get("email", "")
        names = _names(store)
        events.append(("owner_change", f"Owner: {names.get(p.get('owner', ''), '') or 'admins'} → "
                                       f"{names.get(r.owner, '') or 'admins'}", {"from": p.get("owner", ""), "to": r.owner}))
    edited = [k for k in sets if k not in ("stage", "owner", "owner_email")]
    if not sets:
        return {"ok": True, "changed": []}
    sets["updated_at"] = crm.now_iso()
    store.db.people.update_one({"_id": pid}, {"$set": sets})
    for kind, body, meta in events:
        store.add_activity(pid, p.get("company_id", ""), kind, by, body, meta=meta)
    if edited:
        labels = {"first_name": "name", "last_name": "name", "title": "title", "phones": "phone",
                  "linkedin_url": "LinkedIn", "interests": "interests", "not_fit_reason": "not-a-fit reason"}
        store.add_activity(pid, p.get("company_id", ""), "edited", by,
                           "Edited " + ", ".join(sorted({labels.get(k, k) for k in edited})))
    return {"ok": True, "changed": sorted(k for k in sets if k != "updated_at")}


@router.delete("/api/people/{pid}")
def person_delete(pid: str):
    """Delete a lead. One who is in a campaign keeps their campaign history, so only an
    admin can delete them (with it); anyone else removes them from the campaigns first.
    The do-not-contact list is never touched."""
    store = open_store()
    u = _me()
    p = _person_or_404(store, pid, u)
    keys = [d["_id"] for d in store.db.leads.find({"person_id": pid}, {"_id": 1})]
    if keys and not access.is_admin(u):
        raise HTTPException(409, "this lead is in a campaign; remove them from it first (or ask an admin)")
    if keys:
        store.delete_leads(keys)
    store.db.activities.delete_many({"person_id": pid})
    store.db.tasks.delete_many({"person_id": pid})
    store.db.people.delete_one({"_id": pid})
    if p.get("company_id"):
        store.add_activity("", p["company_id"], "person_deleted", _actor(u), f"Deleted lead {_name(p) or p.get('email', '')}")
    return {"ok": True, "enrollments_deleted": len(keys)}


class NoteIn(BaseModel):
    body: str


def _note_body(b: str) -> str:
    body = (b or "").strip()
    if not body:
        raise HTTPException(400, "the note is empty")
    if len(body) > crm.NOTE_MAX:
        raise HTTPException(413, f"notes are limited to {crm.NOTE_MAX} characters")
    return body


@router.post("/api/people/{pid}/notes")
def person_note(pid: str, r: NoteIn):
    store = open_store()
    u = _me()
    p = _person_or_404(store, pid, u)
    a = store.add_activity(pid, p.get("company_id", ""), "note", _actor(u), _note_body(r.body))
    return {"id": str(a["_id"]), "at": a["at"]}


def _activity_or_404(store, aid: str, u: dict) -> dict:
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        oid = ObjectId(aid)
    except (InvalidId, TypeError):
        raise HTTPException(404, "not found")
    a = store.db.activities.find_one({"_id": oid})
    if not a or a.get("type") != "note":
        raise HTTPException(404, "not found")
    if a.get("person_id"):
        _person_or_404(store, a["person_id"], u)
    else:
        _company_or_404(store, a.get("company_id", ""), u)
    return a


class NotePatch(BaseModel):
    pinned: bool | None = None


@router.patch("/api/notes/{aid}")
def note_update(aid: str, r: NotePatch):
    store = open_store()
    a = _activity_or_404(store, aid, _me())
    if r.pinned is not None:
        store.db.activities.update_one({"_id": a["_id"]}, {"$set": {"pinned": bool(r.pinned)}})
    return {"ok": True}


@router.delete("/api/notes/{aid}")
def note_delete(aid: str):
    """A note's author or an admin can delete it."""
    store = open_store()
    u = _me()
    a = _activity_or_404(store, aid, u)
    if not access.is_admin(u) and (a.get("by") or {}).get("id") != u.get("id"):
        raise HTTPException(403, "only the note's author or an admin can delete it")
    store.db.activities.delete_one({"_id": a["_id"]})
    return {"ok": True}


class EnrollIn(BaseModel):
    people: list[str]
    campaign: str
    force: bool = False      # admins: add even where the campaign rules say no


@router.post("/api/people/enroll")
def people_enroll(r: EnrollIn):
    """Add leads to a campaign (as fresh lead rows its pipeline drafts). The campaign
    rules apply (src/enroll.py) and every refusal comes back with the person's name and
    why; an admin can add anyway (`force`). The do-not-contact list always wins, and
    someone already in that campaign isn't added twice."""
    store = open_store()
    u = _me()
    if not _campaign_visible(store, u, r.campaign):
        raise HTTPException(404, f"campaign '{r.campaign}' not found")
    if len(r.people) > 500:
        raise HTTPException(400, "up to 500 leads at a time")
    people = list(store.db.people.find({"_id": {"$in": list(dict.fromkeys(r.people))}, **_people_filter(u)}))
    if len(people) != len(set(r.people)):
        raise HTTPException(404, "lead not found")
    if r.force and not access.is_admin(u):
        raise HTTPException(403, "only an admin can add someone the campaign rules refuse")
    facts = _Facts(store, [])
    guard = enroll.Guard(store, r.campaign)
    try:
        topics = tagging.topics_of(store.get_campaign(r.campaign) or {})
    except Exception:  # noqa: BLE001  topics are a nicety; never block the add
        topics = []
    added = already = suppressed = 0
    refused: list[dict] = []
    for p in people:
        if facts.suppressed(p.get("email", "")):
            suppressed += 1
            continue
        if store.db.leads.find_one({"person_id": p["_id"], "campaign": r.campaign}, {"_id": 1}):
            already += 1
            continue
        latest = store.db.leads.find_one({"person_id": p["_id"]}, {"lead": 1}, sort=[("pulled_at", -1)])
        base = (latest or {}).get("lead") or {}
        lead = Lead(first_name=p.get("first_name", ""), last_name=p.get("last_name", ""), title=p.get("title", ""),
                    company=p.get("company", ""), company_domain=p.get("company_domain", ""),
                    email=p.get("email", ""), linkedin_url=base.get("linkedin_url") or p.get("linkedin_url", ""),
                    source=base.get("source") or (p.get("source") or {}).get("type") or "manual",
                    raw=base.get("raw") or {})
        code, why = store.upsert_lead(lead, r.campaign, topics, guard=guard, force=r.force)
        if code:
            refused.append({"id": p["_id"], "name": _name(p) or p.get("email", ""), "code": code, "why": why})
            continue
        added += 1
    return {"added": added, "already": already, "suppressed": suppressed, "refused": refused}


# --- companies --------------------------------------------------------------------
def _is_customer(c: dict, customers: set) -> bool:
    return any(d in customers for d in [c.get("domain") or ""] + list(c.get("domains") or []) if d)


def _company_rows(store, u: dict) -> list[dict]:
    if access.is_admin(u):
        return list(store.db.companies.find({}))
    uid = u.get("id") or "\0"
    mine = store.db.people.distinct("company_id", {"owner": uid})
    return list(store.db.companies.find({"$or": [{"owner": uid}, {"_id": {"$in": mine}}]}))


@router.get("/api/companies")
def companies_list():
    store = open_store()
    u = _me()
    comps = _company_rows(store, u)
    cids = [c["_id"] for c in comps]
    pf = {"company_id": {"$in": cids}, **_people_filter(u)}
    people = list(store.db.people.find(pf, {"company_id": 1, "email": 1, "stage": 1}))
    enr = _enrollments(store, [p["_id"] for p in people] if not access.is_admin(u) else None)
    facts = _Facts(store, None if access.is_admin(u) else [e["_id"] for es in enr.values() for e in es],
                   [p["_id"] for p in people])
    by_company: dict[str, list[str]] = {}
    for p in people:
        st = p.get("stage") or facts.lead_stage(p, enr.get(p["_id"], []))
        by_company.setdefault(p["company_id"], []).append(st)
    names = _names(store)
    customers = {d["_id"] for d in store.db.customers.find({}, {"_id": 1})}
    out = []
    for c in comps:
        stages = by_company.get(c["_id"], [])
        auto = "Customer" if _is_customer(c, customers) else crm.derived_company_stage(stages)
        loc = ", ".join(x for x in (c.get("city"), c.get("state"), c.get("country")) if x)
        out.append({"id": c["_id"], "name": c.get("name", ""), "domain": c.get("domain", ""),
                    "industry": c.get("industry", ""), "employees": c.get("employees"), "location": loc,
                    "owner": c.get("owner", ""), "owner_name": names.get(c.get("owner", ""), ""),
                    "stage": c.get("stage") or auto, "stage_auto": not c.get("stage"),
                    "people": len(stages),
                    "engaged": sum(1 for s in stages if s in ("Replied", "Interested", "Meeting booked")),
                    "contacted": sum(1 for s in stages if s != "New")})
    return {"companies": out}


@router.get("/api/companies/{cid}")
def company_detail(cid: str):
    store = open_store()
    u = _me()
    c = _company_or_404(store, cid, u)
    all_people = list(store.db.people.find({"company_id": cid}))
    visible = [p for p in all_people if access.is_admin(u) or p.get("owner") == u.get("id")]
    hidden = [p for p in all_people if p not in visible]
    pids = [p["_id"] for p in visible]
    enr = _enrollments(store, pids)
    es_all = [e for es in enr.values() for e in es]
    facts = _Facts(store, [e["_id"] for e in es_all], pids)
    names = _names(store)
    contacts = []
    for p in visible:
        es = enr.get(p["_id"], [])
        auto = facts.lead_stage(p, es)
        contacts.append({"id": p["_id"], "name": _name(p), "title": p.get("title", ""), "email": p.get("email", ""),
                         "stage": p.get("stage") or auto, "stage_auto": not p.get("stage"),
                         "owner_name": names.get(p.get("owner", ""), ""),
                         "emails_sent": sum(1 for e in es if e["_id"] in facts.sent),
                         "replied": any(e["_id"] in facts.replies for e in es),
                         "linkedin_url": p.get("linkedin_url", "")})
    others: dict[str, int] = {}
    for p in hidden:
        n = names.get(p.get("owner", ""), "") or "an admin"
        others[n] = others.get(n, 0) + 1
    customers = {d["_id"] for d in store.db.customers.find({}, {"_id": 1})}
    auto = "Customer" if _is_customer(c, customers) else crm.derived_company_stage([x["stage"] for x in contacts])
    who = {p["_id"]: _name(p) for p in visible}
    return {
        "id": c["_id"], "name": c.get("name", ""), "domain": c.get("domain", ""), "domains": c.get("domains") or [],
        "industry": c.get("industry", ""), "employees": c.get("employees"), "revenue": c.get("revenue", ""),
        "city": c.get("city", ""), "state": c.get("state", ""), "country": c.get("country", ""),
        "phone": c.get("phone", ""), "linkedin_url": c.get("linkedin_url", ""), "website_url": c.get("website_url", ""),
        "naics_codes": c.get("naics_codes") or [], "sic_codes": c.get("sic_codes") or [],
        "founded_year": c.get("founded_year"),
        "owner": c.get("owner", ""), "owner_name": names.get(c.get("owner", ""), ""),
        "stage": c.get("stage") or auto, "stage_auto": not c.get("stage"), "stage_derived": auto,
        "tier": c.get("tier", ""), "stream": c.get("stream", ""), "trigger": c.get("trigger", ""),
        "not_fit_reason": c.get("not_fit_reason", ""),
        "contacts": contacts, "others": [{"owner": k, "count": v} for k, v in sorted(others.items())],
        "timeline": _timeline(store, pids, cid, es_all, facts, who=who)}


class CompanyPatch(BaseModel):
    name: str | None = None
    phone: str | None = None
    stage: str | None = None
    tier: str | None = None
    stream: str | None = None
    trigger: str | None = None
    not_fit_reason: str | None = None
    owner: str | None = None


@router.patch("/api/companies/{cid}")
def company_update(cid: str, r: CompanyPatch):
    store = open_store()
    u = _me()
    c = _company_or_404(store, cid, u)
    if not access.is_admin(u) and c.get("owner") != u.get("id"):
        raise HTTPException(403, "only the company's owner or an admin can change it")
    by = _actor(u)
    sets: dict = {}
    events: list[tuple[str, str, dict]] = []
    for f, n in (("name", 160), ("phone", 40), ("trigger", 300), ("not_fit_reason", 300)):
        v = getattr(r, f)
        if v is not None and _clip(v, n) != c.get(f, ""):
            sets[f] = _clip(v, n)
    if r.tier is not None and r.tier != c.get("tier", ""):
        if r.tier not in ("", "A", "B", "C"):
            raise HTTPException(400, "tier is A, B or C")
        sets["tier"] = r.tier
    if r.stream is not None and r.stream != c.get("stream", ""):
        if r.stream not in ("", "safety", "ops", "scl"):
            raise HTTPException(400, "stream is safety, ops or scl")
        sets["stream"] = r.stream
    if r.stage is not None and r.stage != (c.get("stage") or ""):
        if r.stage and r.stage not in crm.COMPANY_STAGES:
            raise HTTPException(400, "not a company stage")
        sets["stage"] = r.stage
        events.append(("stage_change", f"Company stage: {c.get('stage') or 'automatic'} → {r.stage or 'automatic'}",
                       {"from": c.get("stage") or "", "to": r.stage}))
    if r.owner is not None and r.owner != (c.get("owner") or ""):
        if not access.is_admin(u):
            raise HTTPException(403, "only an admin can change a company's owner")
        o = _owner_check(store, r.owner)
        sets["owner"], sets["owner_email"] = r.owner, o.get("email", "")
        names = _names(store)
        events.append(("owner_change", f"Company owner: {names.get(c.get('owner', ''), '') or 'admins'} → "
                                       f"{names.get(r.owner, '') or 'admins'}", {"from": c.get("owner", ""), "to": r.owner}))
    if not sets:
        return {"ok": True, "changed": []}
    sets["updated_at"] = crm.now_iso()
    store.db.companies.update_one({"_id": cid}, {"$set": sets})
    for kind, body, meta in events:
        store.add_activity("", cid, kind, by, body, meta=meta)
    edited = [k for k in sets if k not in ("stage", "owner", "owner_email", "updated_at")]
    if edited:
        store.add_activity("", cid, "edited", by, "Edited " + ", ".join(sorted(edited)).replace("_", " "))
    return {"ok": True, "changed": sorted(k for k in sets if k != "updated_at")}


@router.post("/api/companies/{cid}/notes")
def company_note(cid: str, r: NoteIn):
    store = open_store()
    u = _me()
    _company_or_404(store, cid, u)
    a = store.add_activity("", cid, "note", _actor(u), _note_body(r.body))
    return {"id": str(a["_id"]), "at": a["at"]}


# --- existing Knowella customers (the customer guard, 35a) ---------------------------
# Until Knowella's own data can be read (decision #22), admins keep this list by hand.
# Anyone at a listed domain is never added to a campaign, and the company shows as a
# Customer.
@router.get("/api/customers")
def customers_list():
    store = open_store()
    return [{"domain": d["_id"], "name": d.get("name", ""), "source": d.get("source", ""),
             "by": (d.get("by") or {}).get("label", ""), "at": d.get("at", "")} for d in store.list_customers()]


class CustomersIn(BaseModel):
    domains: list[str]
    name: str = ""


@router.post("/api/customers")
def customers_add(r: CustomersIn):
    if not r.domains or len(r.domains) > 500:
        raise HTTPException(400, "give 1 to 500 domains")
    store = open_store()
    added = store.add_customers(r.domains, _clip(r.name, 120), _actor(_me()))
    return {"added": added, "ignored": len(r.domains) - len(added)}


@router.delete("/api/customers/{domain}")
def customers_remove(domain: str):
    if not open_store().remove_customer(crm.norm_domain(domain) or domain):
        raise HTTPException(404, "not on the list")
    return {"ok": True}
