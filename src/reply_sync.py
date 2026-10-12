"""Replies, reply classes, deliveries and bounces from Apollo, on a schedule.

The October pipeline audit (docs/pipeline-audit-2026-10.md, C2) found reply capture
broken: replies were read only when someone opened the Inbox, at most 1,000 messages
a sequence, and Apollo's own per-message `reply_class` was ignored, so every reply
counted as "other" and outcomes never moved. This syncs every message of every
campaign's sequence, fully paged, in the background:

- each sent message is kept (`messages`: step, delivery time, reply flag and class,
  bounce), so a lead's timeline shows every step on the day it went out;
- a reply is recorded with its class (`replies.label`), which moves the lead's stage
  to Interested / Not interested / Wrong person, and feeds the campaign outcomes;
- a bounce marks the lead row bounced and the address undeliverable.

Apollo's API returns only the messages we sent (a reply exists as `replied` on ours),
so there is still no reply text; that comes with the move to Graph (phase 2).

Apollo allows ~400 calls an hour per endpoint, shared with everything else the app
does. A run pages slowly, stops when Apollo says the hour's budget is low, and the
next run starts with the sequences synced longest ago.
"""
from __future__ import annotations

import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone

SYNC_HOURS = 6
FIRST_RUN_DELAY = 300          # seconds after startup
PAGE_SIZE = 50
PAGE_PAUSE = 0.4               # seconds between pages
MIN_HOURLY_LEFT = 120          # stop when fewer calls than this are left this hour
MIN_DAY_LEFT = 300
SETTING = "reply_sync"
ENDPOINT = "/emailer_messages/search"

# Apollo's reply classes -> ours. The audit's definition of interested.
APOLLO_LABEL = {
    "willing_to_meet": "interested", "follow_up_question": "interested", "person_referral": "interested",
    "not_interested": "not_interested", "out_of_office": "ooo", "wrong_person": "wrong_person",
    "unsubscribe": "opt_out", "do_not_contact": "opt_out",
}
_LABEL_RANK = {"opt_out": 5, "interested": 4, "not_interested": 3, "wrong_person": 2, "other": 1, "": 0}
_lock = threading.Lock()
_started = False


def label_for(reply_class: str | None) -> str:
    return APOLLO_LABEL.get((reply_class or "").strip().lower(), "other")


def _budget_low() -> bool:
    """True when Apollo's last word on this endpoint (its response headers) says the
    budget is low. A reading older than 10 minutes is ignored: otherwise a run that
    stopped on a low budget would leave that reading behind, and every later run would
    stop before making the call that refreshes it."""
    from .integrations import apollo_send
    r = apollo_send.RATE_LIMITS.get(ENDPOINT) or {}
    seen = _when(r.get("at"))
    if not seen or (datetime.now(timezone.utc) - datetime.fromisoformat(seen)).total_seconds() > 600:
        return False
    return (r.get("hourly_left") is not None and r["hourly_left"] < MIN_HOURLY_LEFT) or \
           (r.get("day_left") is not None and r["day_left"] < MIN_DAY_LEFT)


def _when(v) -> str:
    if not v:
        return ""
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()
    except ValueError:
        return ""


def record_reply(store, key: str, label: str, apollo_class: str = "") -> bool:
    """A reply on a lead row, with its class. Never downgrades a class already known
    (an Inbox visit that only knows "replied" can't wipe "interested"). Returns True when
    it's the first time this reply is seen."""
    cur = store.db.replies.find_one({"_id": key}, {"label": 1}) or {}
    upd: dict = {"$setOnInsert": {"replied": True, "at": datetime.now(timezone.utc).isoformat()}}
    sets = {}
    if _LABEL_RANK.get(label, 1) >= _LABEL_RANK.get(cur.get("label") or "", 0):
        sets["label"] = label
    if apollo_class:
        sets["apollo_class"] = apollo_class
    if sets:
        upd["$set"] = sets
    r = store.db.replies.update_one({"_id": key}, upd, upsert=True)
    return r.upserted_id is not None


def _sequences(store) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name in store.campaign_names():
        sid = (((store.get_campaign(name) or {}).get("sending") or {}).get("sequence_id") or "").strip()
        if sid and not sid.startswith("<"):
            out.setdefault(sid, []).append(name)
    return out


def _directory(store, campaigns: list[str]) -> dict[str, str]:
    """Recipient email -> lead row key, for the campaigns sending through one sequence."""
    out: dict[str, str] = {}
    for c in campaigns:
        for d in store.db.leads.find({"campaign": c}, {"lead.email": 1}):
            e = ((d.get("lead") or {}).get("email") or "").strip().lower()
            if e:
                out.setdefault(e, d["_id"])
    return out


def _handle(store, m: dict, directory: dict, sid: str, st: Counter, dry: bool = False) -> None:
    """One Apollo message. `dry`: count what would change, write nothing."""
    from .integrations import apollo_send
    if apollo_send.is_inbound(m):
        return
    email = (m.get("to_email") or "").strip().lower()
    key = directory.get(email)
    if not key:
        st["unmatched"] += 1
        return
    st["messages"] += 1
    reply_class = m.get("reply_class") or ""
    doc = {"enrollment": key, "campaign": key.split("::", 1)[0], "sequence": sid,
           "step": m.get("campaign_position"), "status": m.get("status") or "",
           "delivered_at": _when(m.get("completed_at")) if (m.get("status") == "completed") else "",
           "replied": bool(m.get("replied")), "reply_class": reply_class, "bounce": bool(m.get("bounce")),
           "failed": bool(m.get("failed_at")), "synced_at": datetime.now(timezone.utc).isoformat()}
    if not dry:
        store.db.messages.update_one({"_id": str(m.get("id"))}, {"$set": doc}, upsert=True)
    if doc["bounce"]:
        st["bounced"] += 1
        if dry:
            row = store.db.leads.find_one({"_id": key}, {"status": 1}) or {}
            if row.get("status") not in ("bounced", "suppressed"):
                st["would_mark_bounced"] += 1
        else:
            store.save_verify(email, "undeliverable")
            store.db.leads.update_one({"_id": key, "status": {"$ne": "suppressed"}}, {"$set": {"status": "bounced"}})
    if doc["replied"]:
        label = label_for(reply_class)
        if label == "ooo":                     # an out-of-office is not a reply
            st["out_of_office"] += 1
            return
        if dry:
            cur = store.db.replies.find_one({"_id": key}, {"label": 1})
            if cur is None:
                st["new_replies"] += 1
            elif (cur.get("label") or "") != label and _LABEL_RANK.get(label, 1) >= _LABEL_RANK.get(cur.get("label") or "", 0):
                st["would_relabel"] += 1
                st[f"relabel_{cur.get('label') or 'none'}_to_{label}"] += 1
        elif record_reply(store, key, label, reply_class):
            st["new_replies"] += 1
        st[f"reply_{label}"] += 1
        if label == "opt_out":
            st["opt_outs"] += 1
            if not store.is_suppressed(email):
                if dry:
                    st["would_suppress"] += 1
                else:
                    store.suppress(email, "asked to stop (Apollo reply class)")


def run(store, only: list[str] | None = None, dry: bool = False) -> dict:
    """One pass over every campaign sequence (or `only` these sequence ids), oldest
    synced first. Returns what it did; also saved as the reply_sync setting. `dry`
    reads Apollo the same way but writes nothing and saves nothing: it reports what a
    real run would change."""
    from .integrations import apollo_send
    if not apollo_send.has_key():
        return {"skipped": "no Apollo key"}
    if not _lock.acquire(blocking=False):
        return {"skipped": "a sync is already running"}
    try:
        st: Counter = Counter()
        state = store.get_setting(SETTING) or {}
        last = state.get("sequences") or {}
        seqs = _sequences(store)
        order = sorted((s for s in seqs if not only or s in only), key=lambda s: last.get(s, ""))
        stopped = ""
        for sid in order:
            directory = _directory(store, seqs[sid])
            page, done = 1, False
            while not done:
                if _budget_low():
                    stopped = "Apollo's hourly or daily budget is low; the next run carries on"
                    break
                data = apollo_send._request("POST", ENDPOINT, os.environ.get("APOLLO_API_KEY"),
                                            {"emailer_campaign_ids": [sid], "per_page": PAGE_SIZE, "page": page})
                st["pages"] += 1
                batch = data.get("emailer_messages", []) or []
                for m in batch:
                    _handle(store, m, directory, sid, st, dry)
                done = len(batch) < PAGE_SIZE
                page += 1
                if not done:
                    time.sleep(PAGE_PAUSE)
            if stopped:
                break
            last[sid] = datetime.now(timezone.utc).isoformat()
            st["sequences"] += 1
        result = {**dict(st), "at": datetime.now(timezone.utc).isoformat(), "stopped": stopped}
        if dry:
            return {**result, "dry_run": True}
        store.set_setting(SETTING, {"sequences": last, "last": result})
        apollo_send._msg_cache.clear()          # the Inbox reads fresh next time
        return result
    finally:
        _lock.release()


def start(open_store) -> None:
    """The background loop: one run a few minutes after startup, then every 6 hours.
    Single uvicorn process (Dockerfile), so one loop; a second one would just find the
    lock taken."""
    global _started
    if _started or os.environ.get("REPLY_SYNC_OFF"):
        return
    _started = True

    def loop():
        time.sleep(FIRST_RUN_DELAY)
        while True:
            try:
                r = run(open_store())
                print(f"[reply-sync] {r}")
            except Exception as e:  # noqa: BLE001  never let the loop die
                print(f"[reply-sync] failed: {e}")
            time.sleep(SYNC_HOURS * 3600)

    threading.Thread(target=loop, daemon=True, name="reply-sync").start()


if __name__ == "__main__":
    # python -m src.reply_sync          one dry run: what a real run would change
    # python -m src.reply_sync --apply  one real run now
    import json
    import sys
    from .store import open_store
    out = run(open_store(), dry="--apply" not in sys.argv[1:])
    print(json.dumps(out, indent=1, sort_keys=True))
