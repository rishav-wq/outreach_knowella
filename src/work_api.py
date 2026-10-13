"""Routes for a BDR's daily work (src/work.py): logging a call, LinkedIn touch or email
on a lead; tasks; and the Today page.

Scope follows the Library's (src/crm_api.py): you log on and add tasks to the leads you
can see. Tasks belong to one person; sales users see and change their own, admins
everyone's. Anything outside your scope answers 404.
"""
from __future__ import annotations

from datetime import timedelta

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import access, crm, work
from .crm_api import _actor, _me, _name, _names, _person_or_404
from .store import open_store

router = APIRouter()
LIST_MAX = 300


def _day(s: str, what: str = "date"):
    try:
        return work.parse_day(s)
    except (ValueError, TypeError):
        raise HTTPException(400, f"{what} must be a date (YYYY-MM-DD)")


def _clip(s: str, n: int) -> str:
    return (s or "").strip()[:n]


def _task_or_404(store, tid: str, u: dict) -> dict:
    try:
        oid = ObjectId(tid)
    except (InvalidId, TypeError):
        raise HTTPException(404, "task not found")
    t = store.db.tasks.find_one({"_id": oid})
    if not t or (not access.is_admin(u) and t.get("owner") != u.get("id")):
        raise HTTPException(404, "task not found")
    return t


def _task_out(t: dict, people: dict, names: dict) -> dict:
    p = people.get(t.get("person_id", "")) or {}
    return {"id": str(t["_id"]), "kind": t.get("kind", "todo"), "title": t.get("title", ""),
            "due": t.get("due", ""), "status": t.get("status", "open"),
            "person_id": t.get("person_id", ""), "person_name": _name(p) if p else "",
            "person_title": p.get("title", ""), "company": p.get("company", ""),
            "company_id": t.get("company_id", ""),
            "owner": t.get("owner", ""), "owner_name": names.get(t.get("owner", ""), ""),
            "created_at": t.get("created_at", ""), "done_at": t.get("done_at", "")}


def _people_of(store, tasks: list[dict]) -> dict:
    ids = list({t.get("person_id") for t in tasks if t.get("person_id")})
    return {p["_id"]: p for p in store.db.people.find(
        {"_id": {"$in": ids}}, {"first_name": 1, "last_name": 1, "title": 1, "company": 1})}


def _new_task(store, u: dict, owner: dict, kind: str, title: str, due: str, person: dict | None) -> dict:
    now = crm.now_iso()
    doc = {"_id": ObjectId(), "owner": owner.get("id", ""), "owner_email": owner.get("email", ""),
           "kind": kind, "title": title, "due": due, "status": "open",
           "person_id": (person or {}).get("_id", ""), "company_id": (person or {}).get("company_id", ""),
           "created_at": now, "created_by": _actor(u)}
    store.db.tasks.insert_one(doc)
    return doc


def _close_task(store, t: dict, u: dict, status: str) -> None:
    store.db.tasks.update_one({"_id": t["_id"]}, {"$set": {
        "status": status, "done_at": crm.now_iso() if status != "open" else "",
        "done_by": _actor(u) if status != "open" else {}}})


# --- logging a touch ------------------------------------------------------------------
class LogIn(BaseModel):
    kind: str                       # call | linkedin | email
    outcome: str = ""               # a call's outcome (work.CALL_OUTCOMES)
    action: str = ""                # a LinkedIn touch (work.LINKEDIN_ACTIONS)
    note: str = ""
    not_fit_reason: str = ""        # with outcome not_a_fit: saved on the lead
    task_id: str = ""               # the task this completes
    follow_up_due: str = ""         # YYYY-MM-DD: also add a follow-up task
    follow_up_kind: str = "call"
    follow_up_title: str = ""


@router.post("/api/people/{pid}/log")
def log_touch(pid: str, r: LogIn):
    """Log a call (with its outcome), a LinkedIn touch or an email sent outside the app.
    It goes on the lead's timeline and counts toward today's activity; optionally it
    closes the task it came from and adds the next one."""
    store = open_store()
    u = _me()
    p = _person_or_404(store, pid, u)
    if r.kind not in work.TOUCH_TYPES:
        raise HTTPException(400, "kind must be call, linkedin or email")
    meta: dict = {}
    if r.kind == "call":
        if r.outcome not in work.CALL_OUTCOMES:
            raise HTTPException(400, "pick the call's outcome")
        meta["outcome"] = r.outcome
    elif r.kind == "linkedin":
        if r.action not in work.LINKEDIN_ACTIONS:
            raise HTTPException(400, "pick what you did on LinkedIn")
        meta["action"] = r.action
    note = _clip(r.note, crm.NOTE_MAX)
    reason = _clip(r.not_fit_reason, work.REASON_MAX) if r.outcome == "not_a_fit" else ""
    if reason:
        meta["not_fit_reason"] = reason
    task = None
    if r.task_id:
        task = _task_or_404(store, r.task_id, u)
        if task.get("person_id") and task["person_id"] != pid:
            raise HTTPException(400, "that task is for a different lead")
    follow = None
    if r.follow_up_due:
        _day(r.follow_up_due, "the follow-up date")
        if r.follow_up_kind not in work.TASK_KINDS:
            raise HTTPException(400, "unknown follow-up kind")
    a = store.add_activity(pid, p.get("company_id", ""), work.TOUCH_TYPES[r.kind], _actor(u), note, meta=meta)
    if reason:
        store.db.people.update_one({"_id": pid}, {"$set": {"not_fit_reason": reason, "updated_at": crm.now_iso()}})
    if task is not None and task.get("status") == "open":
        _close_task(store, task, u, "done")
    if r.follow_up_due:
        title = _clip(r.follow_up_title, work.TITLE_MAX) or {
            "call": "Call back", "email": "Send the follow-up email", "linkedin": "LinkedIn follow-up",
            "todo": "Follow up"}[r.follow_up_kind]
        follow = _new_task(store, u, u, r.follow_up_kind, title, r.follow_up_due, p)
    return {"id": str(a["_id"]), "at": a["at"], "task_done": task is not None,
            "follow_up": str(follow["_id"]) if follow else ""}


# --- tasks ------------------------------------------------------------------------------
class TaskIn(BaseModel):
    title: str
    due: str
    kind: str = "todo"
    person_id: str = ""
    owner: str = ""                 # admins: give it to someone else


@router.post("/api/tasks")
def task_create(r: TaskIn):
    store = open_store()
    u = _me()
    title = _clip(r.title, work.TITLE_MAX)
    if not title:
        raise HTTPException(400, "the task needs a title")
    _day(r.due, "the due date")
    if r.kind not in work.TASK_KINDS:
        raise HTTPException(400, "unknown task kind")
    person = _person_or_404(store, r.person_id, u) if r.person_id else None
    owner = u
    if r.owner and r.owner != u.get("id"):
        if not access.is_admin(u):
            raise HTTPException(403, "only an admin can give a task to someone else")
        o = store.get_user(r.owner)
        if not o or not o.get("active", True) or o.get("role") not in ("admin", "sales"):
            raise HTTPException(400, "the task's owner must be an active sales person or admin")
        owner = {"id": o["_id"], "email": o.get("email", "")}
    t = _new_task(store, u, owner, r.kind, title, r.due, person)
    return _task_out(t, _people_of(store, [t]), _names(store))


@router.get("/api/tasks")
def task_list(status: str = "open", owner: str = "me", person: str = ""):
    """Tasks, soonest due first. Sales users get their own; admins pass owner=all or a
    user id. person= narrows to one lead."""
    store = open_store()
    u = _me()
    q: dict = {}
    if status != "all":
        if status not in work.TASK_STATUSES:
            raise HTTPException(400, "status is open, done, skipped or all")
        q["status"] = status
    if access.is_admin(u):
        if owner == "me":
            q["owner"] = u.get("id")
        elif owner != "all":
            q["owner"] = owner
    else:
        q["owner"] = u.get("id") or "\0"
    if person:
        _person_or_404(store, person, u)
        q["person_id"] = person
    tasks = list(store.db.tasks.find(q).sort([("due", 1), ("_id", 1)]).limit(LIST_MAX))
    people, names = _people_of(store, tasks), _names(store)
    return {"tasks": [_task_out(t, people, names) for t in tasks]}


class TaskPatch(BaseModel):
    status: str | None = None
    due: str | None = None
    title: str | None = None


@router.patch("/api/tasks/{tid}")
def task_update(tid: str, r: TaskPatch):
    store = open_store()
    u = _me()
    t = _task_or_404(store, tid, u)
    sets: dict = {}
    if r.title is not None:
        title = _clip(r.title, work.TITLE_MAX)
        if not title:
            raise HTTPException(400, "the task needs a title")
        sets["title"] = title
    if r.due is not None:
        _day(r.due, "the due date")
        sets["due"] = r.due
    if sets:
        store.db.tasks.update_one({"_id": t["_id"]}, {"$set": sets})
    if r.status is not None:
        if r.status not in work.TASK_STATUSES:
            raise HTTPException(400, "status is open, done or skipped")
        if r.status != t.get("status"):
            _close_task(store, t, u, r.status)
    if not sets and r.status is None:
        raise HTTPException(400, "nothing to change")
    t = store.db.tasks.find_one({"_id": t["_id"]})
    return _task_out(t, _people_of(store, [t]), _names(store))


@router.delete("/api/tasks/{tid}")
def task_delete(tid: str):
    store = open_store()
    t = _task_or_404(store, tid, _me())
    store.db.tasks.delete_one({"_id": t["_id"]})
    return {"ok": True}


# --- Today ------------------------------------------------------------------------------
def _owned_campaigns(store, uid: str) -> list[str]:
    return [n for n, o in store.campaign_owners().items() if o == uid]


def _tz(tz: int) -> int:
    if not -14 * 60 <= tz <= 14 * 60:
        raise HTTPException(400, "tz is the browser's time-zone offset in minutes")
    return tz


@router.get("/api/today")
def today(date: str, tz: int = 0, user: str = ""):
    """One person's day: tasks overdue, due today and in the next week; what they've done
    today; and the playbook's targets for where they are on the ramp. Admins can look at
    anyone's day (user=) and also get the team's numbers."""
    store = open_store()
    u = _me()
    day = _day(date)
    lo, hi = work.day_bounds(day, _tz(tz))
    who = u
    if user and user != u.get("id"):
        if not access.is_admin(u):
            raise HTTPException(404, "not found")
        target = store.get_user(user)
        if not target:
            raise HTTPException(404, "not found")
        who = {**target, "id": target["_id"]}
    uid = who.get("id") or "\0"
    record = store.get_user(uid) or who
    start = work.start_of(record)
    week_end = (day + timedelta(days=7)).isoformat()
    open_tasks = list(store.db.tasks.find({"owner": uid, "status": "open"}).sort([("due", 1), ("_id", 1)]))
    overdue = [t for t in open_tasks if t.get("due", "") < date]
    due_today = [t for t in open_tasks if t.get("due", "") == date]
    upcoming = [t for t in open_tasks if date < t.get("due", "") <= week_end]
    shown = overdue[:LIST_MAX] + due_today[:LIST_MAX] + upcoming[:LIST_MAX]
    people, names = _people_of(store, shown), _names(store)
    content = store.latest_training_content(with_html=False) or {}
    targets = content.get("activity_targets")
    if targets is None and content:
        full = store.latest_training_content(with_html=True) or {}
        targets = work.targets_of(full.get("html", ""))
        store.db.training_content.update_one({"_id": content["_id"]}, {"$set": {"activity_targets": targets}})
    r = work.ramp(start, day, targets or {})
    out = {"date": date, "user": {"id": uid, "name": record.get("name", ""), "email": record.get("email", ""),
                                  "start_date": start.isoformat() if start else ""},
           "tasks": {"overdue": [_task_out(t, people, names) for t in overdue[:LIST_MAX]],
                     "today": [_task_out(t, people, names) for t in due_today[:LIST_MAX]],
                     "upcoming": [_task_out(t, people, names) for t in upcoming[:LIST_MAX]],
                     "counts": {"overdue": len(overdue), "today": len(due_today), "upcoming": len(upcoming)}},
           "activity": work.activity(store, uid, lo, hi, _owned_campaigns(store, uid)),
           "ramp": r, "labels": work.CALL_OUTCOMES}
    if access.is_admin(u) and not user:
        team = []
        for x in store.list_users():
            if not x.get("active", True) or x.get("role") not in ("sales", "admin"):
                continue
            mine = store.db.tasks.count_documents({"owner": x["_id"], "status": "open", "due": {"$lt": date}})
            act = work.activity(store, x["_id"], lo, hi, _owned_campaigns(store, x["_id"]))
            if x.get("role") == "admin" and not mine and not any(act.values()):
                continue                # an admin who does no outreach isn't part of the team view
            tr = work.ramp(work.start_of(x), day, targets or {})
            team.append({"id": x["_id"], "name": x.get("name", ""), "email": x.get("email", ""),
                         "role": x.get("role", ""), "activity": act, "overdue": mine,
                         "targets": tr["targets"], "week": tr["week"]})
        out["team"] = team
    return out
