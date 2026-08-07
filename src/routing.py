"""Which campaign does this lead belong to?

A signal arrives knowing nothing about our campaigns — an OSHA citation says "big
rig parts distributer", not "knowdoc-freight". This scores it against what each
campaign already declares it wants (its ICP industries, Apollo keywords, titles and
the product it sells) and returns the best fit WITH the terms that matched.

The terms matter as much as the answer. An auto-route you can't audit is one nobody
trusts, and the honest outcome is often "nothing matched" — which is information
about the campaign's config, not a reason to guess. Nothing here silently picks.
"""
from __future__ import annotations

import re
from functools import lru_cache

# Industry vocabulary is thin in most campaign configs, so a handful of obvious
# synonyms are expanded — "trucking" should match a release that says "freight
# carrier". Kept deliberately small: every entry is a claim about our market, and a
# wrong one routes a lead to the wrong pitch.
_EXPAND = {
    "trucking": ["truck", "trucking", "carrier", "fleet", "big rig", "tractor-trailer", "hauling"],
    "freight": ["freight", "shipment", "load", "drayage", "logistics"],
    "logistics": ["logistics", "warehouse", "distribution", "3pl", "supply chain"],
    "transportation": ["transportation", "transit", "motor carrier"],
    "distribution": ["distribution", "distributer", "distributor", "wholesale"],
    "construction": ["construction", "contractor", "roofing", "excavation", "jobsite",
                     "job site", "scaffold", "framing", "concrete"],
    "manufacturing": ["manufacturing", "manufacturer", "plant", "mill", "factory",
                      "production facility", "processing"],
    "ergonomics": ["ergonomic", "ergonomics", "musculoskeletal", "lifting", "repetitive motion"],
}
# Weighted by how much each field really says about fit. An industry match is a
# statement about the company; a title match is about one person and often incidental.
_WEIGHTS = {"industry": 3.0, "keyword": 3.0, "product": 1.5, "title": 1.0}


def _terms_for(cfg: dict) -> list[tuple[str, str, float]]:
    """(term, label, weight) for one campaign, from what it already declares."""
    icp = cfg.get("icp") or {}
    ap = cfg.get("apollo") or {}
    out: list[tuple[str, str, float]] = []
    seen: set[str] = set()

    def add(raw: str, kind: str):
        t = (raw or "").strip().lower()
        if len(t) < 3:
            return
        for variant in _EXPAND.get(t, [t]):
            if variant not in seen:
                seen.add(variant)
                out.append((variant, kind, _WEIGHTS[kind]))

    for v in (icp.get("industries") or []):
        add(v, "industry")
    for v in (ap.get("keywords") or []):
        add(v, "keyword")
    for v in (icp.get("titles") or []):
        add(v, "title")
    offer = cfg.get("offer") or {}
    for word in re.findall(r"[A-Za-z]{4,}", str(offer.get("product") or "")):
        add(word, "product")
    return out


@lru_cache(maxsize=2048)
def _word_re(term: str):
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", term) if p]
    return re.compile(r"\b" + r"[\s\-]+".join(parts) + r"s?\b", re.I)


def score(text: str, cfg: dict) -> tuple[float, list[str]]:
    """How well this text fits one campaign, and which terms said so."""
    blob = text or ""
    total, why = 0.0, []
    for term, kind, weight in _terms_for(cfg):
        if _word_re(term).search(blob):
            total += weight
            if term not in why:
                why.append(term)
    return total, why[:5]


def suggest(text: str, configs: dict[str, dict], minimum: float = 3.0) -> dict:
    """Best campaign for this text: {campaign, score, why, alternatives}.

    `campaign` is empty when nothing clears the bar — said plainly rather than
    defaulting to whichever campaign happens to sort first. A blank answer usually
    means that campaign has no industries or keywords configured, which is worth
    knowing and worth fixing.
    """
    ranked = []
    for name, cfg in configs.items():
        s, why = score(text, cfg)
        if s > 0:
            ranked.append({"campaign": name, "score": round(s, 1), "why": why})
    ranked.sort(key=lambda r: r["score"], reverse=True)
    best = ranked[0] if ranked and ranked[0]["score"] >= minimum else None
    return {
        "campaign": best["campaign"] if best else "",
        "score": best["score"] if best else 0,
        "why": best["why"] if best else [],
        "alternatives": [r for r in ranked if not best or r["campaign"] != best["campaign"]][:3],
    }
