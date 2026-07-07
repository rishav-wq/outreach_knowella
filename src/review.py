"""Human-in-the-loop review checkpoint (file-based, no UI needed).

  run (dry-run)              → drafts land in the outbox, status 'queued'
  review --export reviews.csv → writes them to a CSV with a blank 'decision' column
  [you fill decision = approve / reject per row]
  review --import reviews.csv → records decisions
  run --send                  → pushes ONLY approved leads to Apollo

So the irreversible step (sending) can't happen for any lead you didn't approve.
"""
from __future__ import annotations

import csv

from .store import Store

_APPROVE = {"approve", "approved", "yes", "y", "1", "true", "ok"}
_REJECT = {"reject", "rejected", "no", "n", "0", "false"}
FIELDS = ["key", "name", "company", "verdict", "decision", "subject", "body"]


def export_for_review(store: Store, cfg: dict, path: str) -> int:
    rows = []
    for lead in store.leads(cfg["name"]):
        ob = store.get_outbox(lead.key)
        if not ob:
            continue
        rows.append({
            "key": lead.key,
            "name": lead.full_name,
            "company": lead.company,
            "verdict": ob["verdict"],
            "decision": store.get_review(lead.key) or "",
            "subject": ob["subject"],
            "body": ob["body"],
        })
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def import_reviews(store: Store, cfg: dict, path: str) -> tuple[int, int]:
    approved = rejected = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row.get("key") or "").strip()
            decision = (row.get("decision") or "").strip().lower()
            if not key:
                continue
            if decision in _APPROVE:
                store.set_review(key, "approved")
                approved += 1
            elif decision in _REJECT:
                store.set_review(key, "rejected")
                rejected += 1
    return approved, rejected
