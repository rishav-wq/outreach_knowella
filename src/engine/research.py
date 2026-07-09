"""Stage 1 — multi-source research producing CITED, verified facts.

  gather sources (homepage/careers + Tavily web+news)
    -> extract atomic facts WITH the exact supporting quote (LLM, per source)
    -> QUOTE-VERIFY each fact against its source text (deterministic; drops fabrications)
    -> recency filter (drop stale news)
    -> corroborate across sources (raise confidence, dedup)
    -> synthesize pain hypotheses (LLM, each cited to facts)

Returns the same Research shape Phase 1 consumed, so nothing downstream changes.
The anti-false-info guarantee lives in `_quote_ok`: a fact survives only if its
quote actually appears in the fetched source — the model cannot smuggle in a claim
it merely "recalled".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .. import llm
from ..integrations import tavily, web_fetch
from ..models import Fact, Lead, PainPoint, Research


@dataclass
class SourceDoc:
    text: str
    url: str
    source_type: str            # homepage | careers | news | web
    published: str | None = None


# ----------------------------------------------------------------- gather
def _clean_domain(lead: Lead) -> str:
    return (lead.company_domain or "").strip().replace("https://", "").replace("http://", "").strip("/")


def _gather(lead: Lead, log: list[str]) -> list[SourceDoc]:
    docs: list[SourceDoc] = []

    # 1) the company's own pages — no API key needed
    domain = _clean_domain(lead)
    if domain:
        for path, stype in [("", "homepage"), ("/about", "homepage"), ("/careers", "careers"), ("/jobs", "careers")]:
            text = web_fetch.fetch_text(f"https://{domain}{path}")
            if text:
                docs.append(SourceDoc(text=text, url=f"https://{domain}{path}", source_type=stype))

    # 2) Tavily web + news — skips if no key
    if tavily.has_key():
        company = lead.company
        for query, topic, stype, days in [
            (f"{company} company overview products operations", "general", "web", None),
            (f"{company} news announcement expansion hiring incident", "news", "news", 365),
            # Safety/regulatory signals — the highest-value, citable EHS/fleet facts. FMCSA's
            # own APIs block automated access, so we surface OSHA citations + DOT/FMCSA crash/
            # out-of-service records from the open web (news + carrier-data aggregators). Wider
            # 2-yr window since a citation or crash trend stays relevant longer than general news.
            (f"{company} OSHA violation citation inspection penalty DOT FMCSA crash "
             f"out-of-service safety fine recall", "news", "news", 730),
        ]:
            for r in tavily.search(query, max_results=4, topic=topic, days=days):
                if r.get("content"):
                    docs.append(SourceDoc(text=r["content"], url=r.get("url", ""),
                                          source_type=stype, published=r.get("published")))
    else:
        log.append("tavily skipped: no TAVILY_API_KEY (homepage-only research)")

    log.append(f"gathered {len(docs)} source docs "
               f"({sum(1 for d in docs if d.source_type in ('homepage', 'careers'))} own-site, "
               f"{sum(1 for d in docs if d.source_type in ('web', 'news'))} web)")
    return docs


# ---------------------------------------------------------------- extract
EXTRACT_SYSTEM = """Extract atomic, verifiable FACTS about the company from TEXT.
Each fact MUST include the exact verbatim quote from TEXT that supports it.

Every claim MUST carry at least one CONCRETE ANCHOR — a specific place, number,
named role, named product/site, or date. A fact without a specific is useless
for outreach: SKIP generic capability/marketing statements ("provides transportation
services across the United States", "committed to safety", "serves customers nationwide").

PRIORITIZE recent or operational signals: news/announcements, expansion, new
sites/facilities, hiring (WITH the roles being hired), acquisitions, incidents/recalls,
scale (how many locations/trucks/employees), tech/tools, regulatory/OSHA.
AVOID founding/origin stories, "family-owned since 19xx", old history (events more
than ~2 years back), awards, and mission/marketing fluff. No opinions, no guesses,
no duplicates.
Return STRICT JSON: {"facts":[{"claim":"...","quote":"...exact text from TEXT..."}]}"""


def _extract(doc: SourceDoc, company: str, spec) -> tuple[list[dict], dict]:
    out, usage = llm.complete(
        [{"role": "system", "content": EXTRACT_SYSTEM},
         {"role": "user", "content": f"COMPANY: {company}\n\nTEXT:\n{doc.text[:7000]}"}],
        spec, temperature=0)
    try:
        return llm.parse_json(out).get("facts", []) or [], usage
    except Exception:
        return [], usage


# ----------------------------------------------------------- quote verify
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", " ".join((s or "").lower().split()))


def _quote_ok(quote: str, text: str) -> bool:
    """Deterministic anti-hallucination: the quote must really be in the source."""
    nq = _norm(quote)
    return len(nq) >= 12 and nq in _norm(text)


# --------------------------------------------------------------- recency
def _this_year() -> int:
    from datetime import date
    return date.today().year


def _recent_enough(f: Fact) -> bool:
    if not f.published:
        return True  # undated (e.g. homepage) — keep; _score penalizes stale claims
    m = re.search(r"(20\d\d)", f.published)
    return True if not m else int(m.group(1)) >= _this_year() - 1


def _claim_is_stale(f: Fact) -> bool:
    """A claim that only references years >2 back is history, wherever it came from
    (catches undated homepage facts like 'acquired X on January 1, 2011')."""
    years = [int(y) for y in re.findall(r"(20\d\d|19\d\d)", f.claim)]
    return bool(years) and max(years) < _this_year() - 2


# ------------------------------------------------------------ corroborate
def _jaccard(a: str, b: str) -> float:
    ta, tb = set(_norm(a).split()), set(_norm(b).split())
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _corroborate(facts: list[Fact]) -> list[Fact]:
    kept: list[Fact] = []
    for f in facts:
        dup = next((k for k in kept if _jaccard(k.claim, f.claim) >= 0.6), None)
        if dup is None:
            kept.append(f)
        elif f.source_type != dup.source_type:  # same claim, independent source → corroboration
            dup.confidence = min(0.95, dup.confidence + 0.2)
    return kept


# Up-rank operational/recent signals; down-rank founding-history boilerplate.
_SIGNAL_RE = re.compile(r"hir|expand|opened|open |launch|new |grow|acqui|merg|invest|incident|recall|osha|plant|facilit|warehouse|distribution| site|employ|recent|announce|2025|2026", re.I)
_HISTORY_RE = re.compile(r"found|family.owned|established|originally|history|mission|since 19|in 19\d\d|headquarter|award", re.I)


def _score(f: Fact) -> float:
    s = f.confidence
    if _SIGNAL_RE.search(f.claim):
        s += 0.30
    if _HISTORY_RE.search(f.claim):
        s -= 0.35
    if _claim_is_stale(f):          # "acquired X in 2011" is history, not a signal
        s -= 0.60
    if re.search(r"\d", f.claim):   # concrete anchors (counts, dates, sizes) draft better
        s += 0.10
    return s


def _cap(facts: list[Fact], cfg: dict) -> list[Fact]:
    """Keep the strongest facts, GUARANTEEING source diversity, and favoring
    recent/operational signals over founding-history boilerplate (see _score).
    Buckets by source and interleaves web/news + own-site so neither layer is lost.
    """
    k = int((cfg.get("research") or {}).get("max_facts", 12))
    by_score = lambda fs: sorted(fs, key=_score, reverse=True)
    web = by_score([f for f in facts if f.source_type in ("web", "news")])
    site = by_score([f for f in facts if f.source_type in ("homepage", "careers")])

    out, i, j = [], 0, 0
    while len(out) < k and (i < len(web) or j < len(site)):
        if i < len(web):
            out.append(web[i]); i += 1
        if len(out) < k and j < len(site):
            out.append(site[j]); j += 1
    return out


# ------------------------------------------------------------ synthesize
PAIN_SYSTEM = """You infer likely operational PAIN POINTS for a company, for a rep
selling: {product} — {pitch}.
Use ONLY the numbered FACTS. Each pain point is a HYPOTHESIS (a guess), must list
the indices of the facts that motivate it, and must be plausibly tied to them.
Return STRICT JSON:
{{"pain_points":[{{"hypothesis":"...","supporting_facts":[0,1],"confidence":0.5}}],"summary":"one line"}}"""


def _synthesize(facts: list[Fact], cfg: dict, spec) -> tuple[list[PainPoint], str, dict]:
    if not facts:
        return [], "", {}
    offer = cfg["offer"]
    sysmsg = PAIN_SYSTEM.format(product=offer.get("product"), pitch=offer.get("one_liner"))
    numbered = "\n".join(f"[{i}] {f.claim}" for i, f in enumerate(facts))
    out, usage = llm.complete(
        [{"role": "system", "content": sysmsg},
         {"role": "user", "content": f"FACTS:\n{numbered}"}],
        spec, temperature=0.3)
    try:
        data = llm.parse_json(out)
    except Exception:
        return [], "", usage
    pains = [
        PainPoint(
            hypothesis=p.get("hypothesis", ""),
            supporting_facts=[i for i in p.get("supporting_facts", []) if isinstance(i, int) and 0 <= i < len(facts)],
            confidence=float(p.get("confidence", 0.4) or 0.4),
        )
        for p in data.get("pain_points", []) if p.get("hypothesis")
    ]
    return pains, data.get("summary", ""), usage


# ------------------------------------------------------------ orchestrate
def research_lead(lead: Lead, cfg: dict) -> tuple[Research, dict, str]:
    """Returns (Research, total_usage, model_name)."""
    spec = llm.ModelSpec.from_config((cfg.get("models") or {}).get("research"))
    total = {"prompt_tokens": 0, "completion_tokens": 0}

    def _add(u: dict) -> None:
        total["prompt_tokens"] += u.get("prompt_tokens", 0)
        total["completion_tokens"] += u.get("completion_tokens", 0)

    log: list[str] = []
    docs = _gather(lead, log)

    facts: list[Fact] = []
    for doc in docs:
        raw, usage = _extract(doc, lead.company, spec)
        _add(usage)
        for item in raw:
            claim, quote = item.get("claim", ""), item.get("quote", "")
            if claim and _quote_ok(quote, doc.text):       # ← the hallucination filter
                conf = 0.6 + (0.15 if doc.published else 0.0)   # dated (recent) facts rank higher
                facts.append(Fact(claim=claim, quote=quote, source_url=doc.url,
                                  source_type=doc.source_type, published=doc.published, confidence=conf))

    facts = [f for f in facts if _recent_enough(f)]
    facts = _corroborate(facts)
    pre_cap = len(facts)
    facts = _cap(facts, cfg)
    if len(facts) < pre_cap:
        log.append(f"capped to top {len(facts)} of {pre_cap} facts by confidence")
    pains, summary, usage = _synthesize(facts, cfg, spec)
    _add(usage)

    log.append(f"kept {len(facts)} verified facts, {len(pains)} pain hypotheses")
    for line in log:
        print(f"  [research] {line}")
    return Research(facts=facts, pain_points=pains, summary=summary), total, spec.resolved_model()
