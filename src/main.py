"""CLI runner.

  python -m src.main pull --campaign config/my.yaml --apollo   # bring leads in
  python -m src.main run  --campaign config/my.yaml            # research + draft (dry-run)
  python -m src.main run  --campaign config/my.yaml --send     # actually push
  python -m src.main status --campaign config/my.yaml

Sending is OFF by default (dry-run): the only irreversible step is opt-in via --send.
"""
from __future__ import annotations

import argparse
import os
import sys

# Windows consoles default to cp1252 and mangle em-dashes etc.; force UTF-8 output.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from . import config, pipeline, review
from .integrations import apollo, csv_source, enrich
from .store import open_store as _open_store


def open_store(args):
    return _open_store()  # Mongo-only now; the old --db flag is ignored


def cmd_run(args) -> None:
    config.load_env()
    cfg = config.load_campaign(args.campaign)
    store = open_store(args)

    results = pipeline.run(store, cfg, dry_run=not args.send, limit=args.limit,
                           require_review=not args.skip_review)
    for r in results:
        lead, d = r["lead"], r["draft"]
        print(f"\n=== {lead.full_name} @ {lead.company}  [{r['verdict']}] {r['reason']}")
        if d:
            print(f"subject: {d.subject}")
            print(d.body)

    print("\n" + "-" * 60)
    print("status:", store.counts(cfg["name"]))
    print("tokens:", store.token_totals(cfg["name"]))
    if not args.send:
        print("(dry-run — nothing sent. Next: review --export reviews.csv → approve → run --send)")


def cmd_pull(args) -> None:
    config.load_env()
    cfg = config.load_campaign(args.campaign)
    store = open_store(args)

    if args.csv:
        leads, src = csv_source.from_csv(args.csv), f"CSV {args.csv}"
    elif args.apollo:
        leads, credits = apollo.fetch_leads(cfg, limit=args.limit or 250)
        src = f"Apollo ({credits} credits)"
    else:
        raise SystemExit("specify a source: --csv <file>  or  --apollo")

    if args.limit:
        leads = leads[: args.limit]
    for lead in leads:
        lead.source = args.source or ("apollo" if args.apollo else "csv")
        if not lead.company_domain and lead.company:  # enrich missing domains (free, guarded)
            d = enrich.find_domain(lead.company)
            if d:
                lead.company_domain = d
        store.upsert_lead(lead, cfg["name"])
    print(f"pulled {len(leads)} leads from {src} into '{cfg['name']}'")
    print("counts:", store.counts(cfg["name"]))


def cmd_review(args) -> None:
    config.load_env()
    cfg = config.load_campaign(args.campaign)
    store = open_store(args)
    if args.export:
        n = review.export_for_review(store, cfg, args.export)
        print(f"exported {n} drafts to {args.export}")
        print("→ fill the 'decision' column (approve / reject) per row, then: review --import " + args.export)
    elif args.import_:
        a, r = review.import_reviews(store, cfg, args.import_)
        print(f"recorded {a} approved, {r} rejected")
    else:
        raise SystemExit("specify --export <path> or --import <path>")


def cmd_status(args) -> None:
    config.load_env()
    cfg = config.load_campaign(args.campaign)
    store = open_store(args)
    print("status:", store.counts(cfg["name"]))
    print("tokens:", store.token_totals(cfg["name"]))


def main() -> None:
    p = argparse.ArgumentParser(description="Cold-outreach personalization engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="advance leads through the pipeline (research → draft → gate)")
    pr.add_argument("--campaign", required=True)
    pr.add_argument("--db", default="data/outreach.db")
    pr.add_argument("--send", action="store_true", help="actually push to the platform (default: dry-run)")
    pr.add_argument("--skip-review", action="store_true", help="with --send, push without per-lead approval")
    pr.add_argument("--limit", type=int)
    pr.set_defaults(func=cmd_run)

    pp = sub.add_parser("pull", help="ingest leads from a CSV export or Apollo (paid)")
    pp.add_argument("--campaign", required=True)
    pp.add_argument("--csv", help="path to a CSV of leads (e.g. Apollo UI export)")
    pp.add_argument("--apollo", action="store_true", help="pull from Apollo API (needs paid plan)")
    pp.add_argument("--source", default="", help="tag the leads' source (apollo/manual)")
    pp.add_argument("--db", default="data/outreach.db")
    pp.add_argument("--limit", type=int)
    pp.set_defaults(func=cmd_pull)

    pv = sub.add_parser("review", help="export drafts for human approval / import decisions")
    pv.add_argument("--campaign", required=True)
    pv.add_argument("--export", help="write pending drafts to this CSV for review")
    pv.add_argument("--import", dest="import_", help="read approve/reject decisions from this CSV")
    pv.add_argument("--db", default="data/outreach.db")
    pv.set_defaults(func=cmd_review)

    ps = sub.add_parser("status", help="show the funnel + token spend")
    ps.add_argument("--campaign", required=True)
    ps.add_argument("--db", default="data/outreach.db")
    ps.set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
