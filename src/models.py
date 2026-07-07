"""Typed objects passed between pipeline stages."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Lead(BaseModel):
    """A single prospect, as pulled from Apollo (or any source)."""
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    company: str = ""
    company_domain: str = ""
    email: str = ""
    linkedin_url: str = ""
    source: str = ""  # origin: apollo | manual | ...
    raw: dict = Field(default_factory=dict)  # original source payload
    stored_key: str = ""  # row identity as persisted; stamped by the store on load

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def key(self) -> str:
        """Stable identity for dedup + idempotency.

        Once a lead is persisted, its stored row key wins — otherwise setting an
        email on a lead keyed by name|domain would silently change its identity,
        making every subsequent store write target a nonexistent row."""
        return (self.stored_key or self.email or f"{self.full_name}|{self.company_domain}").strip().lower()


class Fact(BaseModel):
    """A RETRIEVED, citable statement — never model-recalled, always from a source.

    `quote` is the exact supporting text from the source; it lets us verify the
    fact actually exists in the fetched document (deterministic anti-hallucination).
    """
    claim: str
    quote: str = ""
    source_url: str = ""
    source_type: str = ""           # homepage | news | job_posting | osha | apollo | ...
    published: str | None = None    # ISO date when known (recency)
    confidence: float = 0.5         # raised by cross-source corroboration


class PainPoint(BaseModel):
    """An INFERENCE derived from facts — not itself a fact. Cited to its facts."""
    hypothesis: str
    supporting_facts: list[int] = Field(default_factory=list)  # indices into Research.facts
    confidence: float = 0.4


class Research(BaseModel):
    facts: list[Fact] = Field(default_factory=list)
    pain_points: list[PainPoint] = Field(default_factory=list)
    summary: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.facts


class Draft(BaseModel):
    subject: str = ""
    body: str = ""
    angle: str = ""                              # one line: why this lead, specifically
    used_facts: list[int] = Field(default_factory=list)  # which facts it leaned on


class GateResult(BaseModel):
    verdict: str = "pass"          # pass | fallback | drop
    reason: str = ""
    draft: Draft | None = None     # possibly a fallback-rewritten draft
