"""Deterministic lead tagging for the master leads library.

Every lead we ever pull is kept forever (see MongoStore.all_leads) and grouped in
the library by two axes:
  - function bucket — which persona the lead is, inferred from their job title
    (safety/EHS, supply chain, operations, else other). Derived on the fly so it
    needs no migration and updates if the rules change.
  - topics — what we pitched them, taken from the campaign's industries/keywords
    and stamped on the lead at pull time.
Both are display/filter aids for reusing leads across future marketing campaigns.
"""
from __future__ import annotations

# Order matters: the FIRST bucket whose keyword appears in the title wins, so
# safety-first — a "Fleet Safety Manager" is a safety lead, not a supply-chain one.
FUNCTION_RULES: list[tuple[str, list[str]]] = [
    ("safety", ["safety", "ehs", "hse", "health and safety", "health & safety",
                "environmental health", "loss prevention", "risk", "compliance", "osha"]),
    ("supply_chain", ["supply chain", "procurement", "purchasing", "logistics", "freight",
                      "fleet", "materials", "warehouse", "distribution", "inventory",
                      "sourcing", "transportation"]),
    ("operations", ["operations", "operating officer", "coo", "plant", "production",
                    "manufacturing", "facility", "facilities", "general manager",
                    "site manager", " ops"]),
]

FUNCTION_LABELS = {
    "safety": "Safety / EHS",
    "supply_chain": "Supply chain",
    "operations": "Operations",
    "other": "Other",
}


def function_of(title: str) -> str:
    """The persona bucket for a job title: safety | supply_chain | operations | other."""
    t = f" {(title or '').lower()} "
    for bucket, kws in FUNCTION_RULES:
        if any(k in t for k in kws):
            return bucket
    return "other"


def topics_of(cfg: dict) -> list[str]:
    """The campaign's subject tags (its industries, else its Apollo keywords)."""
    icp = cfg.get("icp") or {}
    ap = cfg.get("apollo") or {}
    topics = icp.get("industries") or ap.get("keywords") or []
    seen, out = set(), []
    for t in topics:
        s = str(t).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:6]
