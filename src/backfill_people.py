"""Backfill people and companies from the lead rows that exist today (KnowCRM phase 1).

    python -m src.backfill_people            # dry run: what would happen; writes nothing
    python -m src.backfill_people --apply    # link every lead row that isn't linked yet

Safe to run again: rows already linked are skipped, and linking is idempotent. New lead
rows are linked as they're imported (store.upsert_lead), so after one --apply this only
picks up rows an import failed to link.

The dry run predicts the result with the same matching rules as the store (email, then
any other address seen for the person, then Apollo id, then LinkedIn, then name at the
company domain for someone with no email). After --apply the real counts are printed
next to the prediction; they must agree.
"""
from __future__ import annotations

import sys
from collections import Counter

from . import crm

BEFORE = {"id": "", "email": "", "label": "before KnowCRM"}
_PROJ = {"campaign": 1, "pulled_at": 1, "person_id": 1, "lead": 1}


def _rows(store, only_unlinked: bool):
    """Lead rows, oldest first (so each person is created from their earliest sighting),
    with _id breaking ties so the dry run and --apply see the same order. Only ids are
    sorted (full rows carry the Apollo payload, too big to sort in memory); the rows are
    then read 200 at a time."""
    q = {"person_id": {"$exists": False}} if only_unlinked else {}
    ids = [d["_id"] for d in store.db.leads.find(q, {"_id": 1, "pulled_at": 1}).sort([("pulled_at", 1), ("_id", 1)])]
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        got = {d["_id"]: d for d in store.db.leads.find({"_id": {"$in": chunk}}, _PROJ)}
        for k in chunk:
            if k in got:
                yield got[k]


def plan(rows) -> dict:
    """What linking these rows would produce, computed in memory."""
    email, apollo, li, name, has_email = {}, {}, {}, {}, {}
    dom, org = {}, {}
    st, rows_per = Counter(), Counter()
    for r in rows:
        st["rows"] += 1
        lead = r.get("lead") or {}
        ids = crm.identity(lead)
        if not (ids["email"] or ids["apollo_id"] or ids["linkedin"] or ids["name_key"]):
            st["rows_without_identity"] += 1
            continue
        pid = (email.get(ids["email"]) if ids["email"] else None) \
            or (apollo.get(ids["apollo_id"]) if ids["apollo_id"] else None) \
            or (li.get(ids["linkedin"]) if ids["linkedin"] else None)
        if pid is None and not ids["email"] and ids["name_key"]:
            cand = name.get(ids["name_key"])
            if cand is not None and not has_email.get(cand):
                pid = cand
        if pid is None:
            pid = st["people"]
            st["people"] += 1
            has_email[pid] = False
        elif ids["email"] and has_email.get(pid) and email.get(ids["email"]) != pid:
            st["people_with_a_second_email"] += 1
        rows_per[pid] += 1
        if ids["email"]:
            email.setdefault(ids["email"], pid)
            has_email[pid] = True
        if ids["apollo_id"]:
            apollo.setdefault(ids["apollo_id"], pid)
        if ids["linkedin"]:
            li.setdefault(ids["linkedin"], pid)
        if ids["name_key"]:
            name.setdefault(ids["name_key"], pid)
        cid = (dom.get(ids["domain"]) if ids["domain"] else None) \
            or (org.get(ids["apollo_org_id"]) if ids["apollo_org_id"] else None)
        if cid is None and (ids["domain"] or ids["apollo_org_id"]):
            cid = st["companies"]
            st["companies"] += 1
        if cid is None:
            st["rows_without_company"] += 1
        else:
            if ids["domain"]:
                dom.setdefault(ids["domain"], cid)
            if ids["apollo_org_id"]:
                org.setdefault(ids["apollo_org_id"], cid)
    st["people_in_2plus_campaigns"] = sum(1 for n in rows_per.values() if n > 1)
    return dict(st)


def apply(store) -> dict:
    st = Counter()
    for r in _rows(store, only_unlinked=True):
        lead = r.get("lead") or {}
        at = r["pulled_at"].isoformat() if r.get("pulled_at") else ""
        try:
            pid = store.link_person(lead, r["_id"], r.get("campaign", ""), by=BEFORE, enrolled=True, at=at)
            st["linked" if pid else "skipped_no_identity"] += 1
        except Exception as e:  # noqa: BLE001  keep going; report at the end
            st["errors"] += 1
            if st["errors"] <= 5:
                print(f"  error on {r['_id']}: {e}", file=sys.stderr)
    return dict(st)


def main(argv: list[str]) -> int:
    from .store import open_store
    store = open_store()
    predicted = plan(_rows(store, only_unlinked=False))
    print("prediction over all lead rows:", predicted)
    if "--apply" not in argv:
        print("dry run: nothing written. Run with --apply to link.")
        return 0
    before = {"people": store.db.people.count_documents({}), "companies": store.db.companies.count_documents({})}
    done = apply(store)
    after = {"people": store.db.people.count_documents({}), "companies": store.db.companies.count_documents({}),
             "rows_still_unlinked": store.db.leads.count_documents({"person_id": {"$exists": False}})}
    print("applied:", done, "| before:", before, "| after:", after)
    ok = after["people"] == predicted.get("people", 0) and after["companies"] == predicted.get("companies", 0)
    print("matches the prediction" if ok else "DOES NOT MATCH the prediction: check before going on")
    return 0 if ok and not done.get("errors") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
