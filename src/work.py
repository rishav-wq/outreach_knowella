"""A BDR's daily work (KnowCRM phase 2, items 30 and 31, plus "Log call" until calling
inside the app lands in phase 3): calls, LinkedIn touches and emails logged on a lead,
tasks with due dates, and the Today page's numbers against the playbook's targets.

The targets come from the uploaded playbook (its "Starting activity targets" table and
the ramp note under it), read when it's served, so none of its numbers live in this
public repo. Without a playbook, Today shows counts and no targets.

Days are the rep's own: the browser sends its date and time-zone offset, and a day is
local midnight to local midnight. Due dates are plain dates (YYYY-MM-DD) for the same
reason: "due today" means today where the rep is.
"""
from __future__ import annotations

import html as _html
import re
from datetime import date, datetime, timedelta, timezone

# The outcome codes the playbook trains reps to log a call with.
CALL_OUTCOMES = {"no_answer": "No answer", "voicemail": "Voicemail", "gatekeeper": "Gatekeeper",
                 "conversation": "Conversation", "meeting": "Meeting booked", "not_a_fit": "Not a fit"}
CONVERSATIONS = {"conversation", "meeting"}            # a conversation, for the daily count
LINKEDIN_ACTIONS = {"view": "Viewed profile", "follow": "Followed", "comment": "Commented",
                    "connect": "Connection request", "message": "Message or voice note"}
TASK_KINDS = {"call": "Call", "email": "Email", "linkedin": "LinkedIn", "todo": "To-do"}
TASK_STATUSES = ("open", "done", "skipped")
# Activity types a logged touch creates. Any of them makes a lead "Contacted".
TOUCH_TYPES = {"call": "call", "linkedin": "linkedin", "email": "email_logged"}
TARGET_KEYS = ("dials", "convos", "emails", "li", "accts", "mtgs")
TITLE_MAX = 300
REASON_MAX = 300


# --- days ---------------------------------------------------------------------------
def parse_day(s: str) -> date:
    """A YYYY-MM-DD date. ValueError otherwise, or when it's absurdly far off."""
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError("dates are YYYY-MM-DD")
    d = date.fromisoformat(s)
    if not (2020 <= d.year <= 2100):
        raise ValueError("that date is out of range")
    return d


def day_bounds(day: date, tz_minutes: int) -> tuple[str, str]:
    """[start, end) of a local day as UTC ISO strings, comparable with stored times.
    tz_minutes is the browser's getTimezoneOffset(): minutes to add to local time to get
    UTC (India is -330)."""
    lo = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(minutes=tz_minutes)
    return lo.isoformat(), (lo + timedelta(days=1)).isoformat()


# --- targets, read from the playbook --------------------------------------------------
_TARGETS_H = re.compile(r"<h[1-4][^>]*>\s*Starting activity targets\s*</h[1-4]>", re.I)
_ROW = re.compile(r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>", re.S | re.I)
_RAMP = re.compile(r"(\d+)\s*%\s*\(\s*days?\s*(\d+)\s*to\s*(\d+)\s*\)", re.I)
_CALLING = re.compile(r"Calling starts in week\s*(\d+)", re.I)
_FROM_WEEK = re.compile(r"clock starts on the first day of week\s*(\d+)", re.I)
_LABEL_KEYS = (("dials", r"\bdial"), ("convos", r"conversation"), ("emails", r"e-?mail"),
               ("li", r"linked\s*in"), ("accts", r"account"), ("mtgs", r"meeting"))


def _text(s: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))).strip()


def targets_of(page: str) -> dict:
    """{daily: {dials, convos, …}, ramp: [[first day, last day, percent], …],
    targets_from_week, calling_week} from the playbook HTML, or {} if it has no table."""
    m = _TARGETS_H.search(page or "")
    if not m:
        return {}
    end = page.find("</section>", m.end())
    sec = page[m.end(): end if end != -1 else m.end() + 8000]
    daily: dict[str, float] = {}
    for label, n in _ROW.findall(sec):
        t = _text(label).lower()
        for key, pat in _LABEL_KEYS:
            if key not in daily and re.search(pat, t):
                try:
                    daily[key] = float(n)
                except ValueError:
                    pass
                break
    if not daily:
        return {}
    note = _text(sec)
    ramp = sorted([int(lo), int(hi), int(p)] for p, lo, hi in _RAMP.findall(note))
    whole = _text(page)
    calling = _CALLING.search(note) or _CALLING.search(whole)
    first = _FROM_WEEK.search(whole)
    return {"daily": daily, "ramp": ramp, "calling_week": int(calling.group(1)) if calling else 0,
            "targets_from_week": int(first.group(1)) if first else 1}


def ramp(start: date | None, today: date, t: dict) -> dict:
    """Where someone who started on `start` is on the ramp today, and their targets.
    Before the targets' first week: none. Then each band's percentage of the full
    targets; past the last band, all of them. Calls count only from the calling week."""
    daily = (t or {}).get("daily") or {}
    if not daily:
        return {"has_targets": False, "targets": {}, "pct": 0, "week": None, "calling": True, "note": ""}
    if start is None or today < start:
        return {"has_targets": True, "targets": dict(daily), "pct": 100, "week": None, "calling": True,
                "note": "Full targets: no start date is set (an admin sets it on the Team page)."}
    days = (today - start).days
    week = days // 7 + 1
    first_week = max(1, int(t.get("targets_from_week") or 1))
    calling_week = int(t.get("calling_week") or 0)
    calling = not calling_week or week >= calling_week
    if week < first_week:
        return {"has_targets": True, "targets": {k: 0 for k in daily}, "pct": 0, "week": week, "calling": calling,
                "note": f"Week {week}: getting started. Targets begin in week {first_week}."}
    n = days - 7 * (first_week - 1) + 1          # day 1 is the first day of the targets' first week
    bands = t.get("ramp") or []
    pct, note = 100, "Full targets."
    for lo, hi, p in bands:
        if lo <= n <= hi:
            pct, note = p, f"Days {lo} to {hi}: {p}% of the full targets."
            break
    targets = {k: round(v * pct / 100, 1) for k, v in daily.items()}
    if not calling:
        for k in ("dials", "convos"):
            if k in targets:
                targets[k] = 0
        note += f" Calling starts in week {calling_week}."
    return {"has_targets": True, "targets": targets, "pct": pct, "week": week, "calling": calling, "note": note}


def start_of(user: dict) -> date | None:
    """The day someone started: set by an admin on the Team page, else their first sign-in."""
    for v in (user.get("start_date"), (user.get("created_at") or "")[:10]):
        try:
            return parse_day(v)
        except (ValueError, TypeError):
            continue
    return None


# --- what someone did in a day ------------------------------------------------------
def activity(store, uid: str, lo: str, hi: str, campaigns: list[str]) -> dict:
    """The day's counts for one person: dials, conversations, emails, LinkedIn touches,
    new accounts and meetings. Emails are the ones they logged plus every step Apollo
    delivered in their campaigns; accounts are the companies of the leads they added."""
    out = dict.fromkeys(TARGET_KEYS, 0)
    for a in store.db.activities.find({"by.id": uid, "type": {"$in": list(TOUCH_TYPES.values())},
                                       "at": {"$gte": lo, "$lt": hi}}, {"type": 1, "meta": 1}):
        kind, outcome = a.get("type"), (a.get("meta") or {}).get("outcome")
        if kind == "call":
            out["dials"] += 1
            if outcome in CONVERSATIONS:
                out["convos"] += 1
            if outcome == "meeting":
                out["mtgs"] += 1
        elif kind == "linkedin":
            out["li"] += 1
        elif kind == "email_logged":
            out["emails"] += 1
    if campaigns:
        out["emails"] += store.db.messages.count_documents(
            {"campaign": {"$in": campaigns}, "delivered_at": {"$gte": lo, "$lt": hi}})
        prefix = "^(" + "|".join(re.escape(c) for c in campaigns) + ")::"
        out["mtgs"] += store.db.meetings.count_documents({"_id": {"$regex": prefix}, "at": {"$gte": lo, "$lt": hi}})
    out["accts"] = len([c for c in store.db.people.distinct(
        "company_id", {"sourced_by.id": uid, "created_at": {"$gte": lo, "$lt": hi}}) if c])
    return out
