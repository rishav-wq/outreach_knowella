"""Apollo credits a sales user may spend on pulls, per day.

Pulling from Apollo reveals each new contact for about one credit, out of one pool the
whole team shares. Admins pull without a limit. A sales user gets a daily allowance
(admins set it in Settings; 0 turns sales pulls off), so one rep can't empty the pool.

A pull first reserves what it asks for, capped at what's left today; the pull reveals
at most that many contacts; then the reservation is settled to what Apollo actually
charged. Reserving is atomic, so two pulls at once can't both spend the last credits.
If the pull fails part-way the reservation stands: the count may run high, never low.

Usage lives in `credit_usage`, one row per user per day (UTC).
"""
from __future__ import annotations

from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from . import access

SETTING = "apollo_pull_allowance"
DEFAULT_PER_DAY = 100    # per sales user per day; admins change it in Settings
MAX_PER_DAY = 2000       # the most one pull can ask for


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def per_day(store) -> int:
    v = store.get_setting(SETTING)
    try:
        return max(0, min(int((v or {}).get("per_day", DEFAULT_PER_DAY)), MAX_PER_DAY))
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_PER_DAY


def set_per_day(store, n: int) -> int:
    n = max(0, min(int(n), MAX_PER_DAY))
    store.set_setting(SETTING, {"per_day": n})
    return n


def _row_id(uid: str, day: str) -> str:
    return f"{uid}::{day}"


def used_today(store, uid: str) -> int:
    d = store.db.credit_usage.find_one({"_id": _row_id(uid, today())}, {"used": 1})
    return int((d or {}).get("used") or 0)


def allowance(store, user: dict | None) -> dict:
    """What this user may still spend today. Admins and internal code: unlimited."""
    if user is None or access.is_admin(user):
        return {"unlimited": True, "per_day": per_day(store),
                "used": used_today(store, user["id"]) if user else 0, "left": None}
    limit = per_day(store)
    used = used_today(store, user["id"])
    return {"unlimited": False, "per_day": limit, "used": used, "left": max(0, limit - used)}


def reserve(store, user: dict | None, want: int, day: str | None = None) -> int:
    """Set aside up to `want` credits for one pull; returns how many were granted (0 =
    none left today). Admins are granted everything and it's recorded, uncapped. Pass
    the same `day` to settle(), so a pull that runs past midnight settles the right row."""
    want = max(0, int(want))
    if want == 0:
        return 0
    if user is None:
        return want
    uid, day = user["id"], day or today()
    rid = _row_id(uid, day)
    col = store.db.credit_usage
    if access.is_admin(user):
        col.update_one({"_id": rid}, {"$inc": {"used": want, "pulls": 1},
                                      "$setOnInsert": {"user": uid, "day": day}}, upsert=True)
        return want
    limit = per_day(store)
    for _ in range(8):                      # retried only when another pull got in between
        row = col.find_one({"_id": rid})
        used = int((row or {}).get("used") or 0)
        grant = min(want, max(0, limit - used))
        if grant <= 0:
            return 0
        if row is None:
            try:
                col.insert_one({"_id": rid, "user": uid, "day": day, "used": grant, "pulls": 1})
                return grant
            except DuplicateKeyError:
                continue
        # Only if nobody else changed `used` since we read it.
        if col.update_one({"_id": rid, "used": row.get("used", 0)},
                          {"$inc": {"used": grant, "pulls": 1}}).modified_count:
            return grant
    return 0


def settle(store, user: dict | None, reserved: int, spent: int, day: str | None = None) -> None:
    """Correct a reservation to what Apollo charged: unused credits go back."""
    if user is None or reserved <= 0:
        return
    delta = int(spent) - int(reserved)
    if delta:
        store.db.credit_usage.update_one({"_id": _row_id(user["id"], day or today())}, {"$inc": {"used": delta}})


def team_today(store) -> list[dict]:
    """Today's usage by person, for the admin view."""
    rows = list(store.db.credit_usage.find({"day": today()}))
    users = {u["_id"]: u for u in store.db.users.find({"_id": {"$in": [r["user"] for r in rows]}},
                                                      {"email": 1, "name": 1, "role": 1})}
    out = [{"user": r["user"], "name": (users.get(r["user"]) or {}).get("name", ""),
            "email": (users.get(r["user"]) or {}).get("email", ""),
            "role": (users.get(r["user"]) or {}).get("role", ""),
            "used": int(r.get("used") or 0), "pulls": int(r.get("pulls") or 0)} for r in rows]
    return sorted(out, key=lambda r: -r["used"])
