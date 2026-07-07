"""Stage 3 — the safety valve. Decide pass / fallback / drop.

Ordering of badness: a hallucinated personal claim > a generic line > nothing.
Two layers: (1) free deterministic checks, (2) an LLM grounding verifier that
confirms every lead-specific claim traces to a real fact.
"""
from __future__ import annotations

import re

from .. import llm
from ..models import Draft, GateResult, Lead, Research

VERIFY_SYSTEM = """You fact-check a cold sales email for ONE failure mode: does it
invent a specific claim ABOUT THE RECIPIENT'S company/role/situation that the
ALLOWED FACTS don't support?

Classify every sentence; only the first category can fail:
1. RECIPIENT claims (about their company/role/situation) — must be supported by an
   ALLOWED FACT. "Supported" = stated in, paraphrased from, or directly entailed by
   a fact. Reasonable rewording, rounding, or date phrasing ("May 2026" → "last May")
   is STILL supported. Flag ONLY a concrete recipient fact with no basis in the facts.
2. SELLER claims (what the product is or does, its benefits) — ALWAYS allowed. Never flag.
3. PAIN hypotheses phrased tentatively ("teams like yours often...", "scaling X is
   usually hard") — ALWAYS allowed. Never flag.

When a sentence is a reasonable paraphrase of a fact, it is grounded. Be precise,
not trigger-happy: only fabricated recipient facts make it ungrounded.
Return STRICT JSON only:
{"grounded": true|false, "unsupported": ["fabricated recipient claim", ...], "reason": "..."}"""


def _deterministic(draft: Draft, voice: dict) -> str | None:
    if not draft.subject.strip() or not draft.body.strip():
        return "empty subject or body"
    max_words = int(voice.get("max_words", 120))
    if len(draft.body.split()) > max_words:
        return f"too long (> {max_words} words)"
    if re.search(r"\{\{.*?\}\}|\[\[.*?\]\]|<[A-Z_]+>", draft.body):
        return "contains unfilled template tokens"
    if len(re.findall(r"https?://", draft.body)) > 1:
        return "more than one link"
    return None


def _fallback(lead: Lead, cfg: dict) -> Draft:
    offer = cfg["offer"]
    return Draft(
        subject=f"{offer.get('product')} for {lead.company}".strip(),
        body=(
            f"Hi {lead.first_name or 'there'} — {offer.get('one_liner')} "
            f"Worth a quick look? {offer.get('link')}"
        ),
        angle="generic fallback (no/weak research)",
        used_facts=[],
    )


def check(draft: Draft, lead: Lead, research: Research, cfg: dict):
    """Returns (GateResult, usage_dict, model_name)."""
    voice = cfg["voice"]

    # Layer 1 — deterministic (free)
    problem = _deterministic(draft, voice)
    if problem:
        return GateResult(verdict="fallback", reason=problem, draft=_fallback(lead, cfg)), {}, ""

    # No research ⇒ it cannot be genuinely personalized ⇒ safe generic line
    if research.is_empty:
        return GateResult(verdict="fallback", reason="no research", draft=_fallback(lead, cfg)), {}, ""

    # Layer 2 — LLM grounding verifier (cheap, deterministic temperature)
    spec = llm.ModelSpec.from_config((cfg.get("models") or {}).get("quality_gate"))
    offer = cfg["offer"]
    allowed = "\n".join(f"- {f.claim}" for f in research.facts) or "(none)"
    seller = f"{offer.get('product')} — {offer.get('one_liner')}; benefits: {offer.get('value_props')}"
    user = (
        f"ALLOWED FACTS (about the recipient):\n{allowed}\n\n"
        f"SELLER PRODUCT (always allowed to mention):\n{seller}\n\n"
        f"EMAIL BODY:\n{draft.body}"
    )
    text, usage = llm.complete(
        [{"role": "system", "content": VERIFY_SYSTEM}, {"role": "user", "content": user}],
        spec,
        temperature=0,
    )
    model = spec.resolved_model()
    try:
        v = llm.parse_json(text)
    except Exception:
        return GateResult(verdict="fallback", reason="verifier parse error", draft=_fallback(lead, cfg)), usage, model

    if v.get("grounded") is True:
        return GateResult(verdict="pass", reason="grounded"), usage, model

    detail = "; ".join(v.get("unsupported", []))[:200]
    return GateResult(verdict="fallback", reason=f"ungrounded: {detail}", draft=_fallback(lead, cfg)), usage, model
