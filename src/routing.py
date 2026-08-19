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

# What a signal is EVIDENCE OF, and therefore which offer can answer it.
#
# Industry alone routed a fatal OSHA citation at FleetPride to a freight PAPERWORK
# campaign, 6.0 to 1.5, because "big rig" and "distributer" are worth more than
# "safety" and nothing in the scoring knew the citation was about a worker dying.
# The industry says which vertical someone is in; the trigger says which problem
# they have, and only one of those decides whether an offer is relevant at all. A
# worker fatality is not a paperwork problem however much freight the company hauls.
#
# Scored above a single industry match on purpose: being in the right vertical with
# the wrong product is a worse email than the reverse.
_TRIGGER_NEEDS = {
    "osha": ("safety", "ehs", "hse", "incident", "hazard", "injury", "inspection"),
    # Self-filed injury records. Narrower than a citation on purpose: an employer
    # with a pile of overexertion cases has an ergonomics problem specifically, not
    # a generic safety one, and routing it to a paperwork or inspection pitch wastes
    # the one thing that makes this signal worth having.
    "osha_ita": ("ergonomic", "ergonomics", "musculoskeletal", "msd", "injury",
                 "safety", "ehs", "lifting"),
}
_TRIGGER_WEIGHT = 6.0


def _offer_blob(cfg: dict) -> str:
    offer = cfg.get("offer") or {}
    return " ".join(str(x) for x in (
        offer.get("product"), offer.get("one_liner"),
        " ".join(offer.get("value_props") or []),
        (cfg.get("icp") or {}).get("titles") and " ".join((cfg.get("icp") or {})["titles"]),
    ) if x).lower()


def trigger_fit(trigger: str, cfg: dict) -> tuple[float, str]:
    """Can this campaign's offer answer this kind of event? (score, the word that said so)"""
    needs = _TRIGGER_NEEDS.get((trigger or "").lower())
    if not needs:
        return 0.0, ""
    blob = _offer_blob(cfg)
    hit = next((w for w in needs if _word_re(w).search(blob)), "")
    return (_TRIGGER_WEIGHT if hit else 0.0), hit


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


def suggest(text: str, configs: dict[str, dict], minimum: float = 3.0,
            trigger: str = "") -> dict:
    """Best campaign for this text: {campaign, score, why, alternatives}.

    `trigger` is what kind of event this is ('osha'), which decides which offers can
    answer it at all. Without it the routing is industry-only, which is how a worker
    fatality ended up queued against a freight-paperwork pitch.

    `campaign` is empty when nothing clears the bar — said plainly rather than
    defaulting to whichever campaign happens to sort first. A blank answer usually
    means that campaign has no industries or keywords configured, which is worth
    knowing and worth fixing.
    """
    ranked = []
    for name, cfg in configs.items():
        s, why = score(text, cfg)
        tw, hit = trigger_fit(trigger, cfg)
        # The trigger AMPLIFIES a fit; it cannot create one. Ungated, every campaign
        # whose offer merely says "safety" collected 6.0 on an OSHA citation — which
        # swept in the investor and trade-show campaigns, whose product is safety
        # software but whose reader is not an employer that has just been cited.
        if tw and s > 0:
            s += tw
            why = [f"answers {trigger.upper()}: {hit}"] + why
        if s > 0:
            ranked.append({"campaign": name, "score": round(s, 1), "why": why[:5]})
    ranked.sort(key=lambda r: r["score"], reverse=True)
    best = ranked[0] if ranked and ranked[0]["score"] >= minimum else None
    return {
        "campaign": best["campaign"] if best else "",
        "score": best["score"] if best else 0,
        "why": best["why"] if best else [],
        "alternatives": [r for r in ranked if not best or r["campaign"] != best["campaign"]][:3],
    }
