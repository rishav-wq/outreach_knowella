"""Stage 2 — turn cited facts into a grounded, relevant email.

The model may ONLY state lead-specific facts that appear in FACTS. Pain points are
passed as hypotheses and must stay hypotheses. The quality gate verifies compliance
afterward — this stage just produces the best grounded draft it can.
"""
from __future__ import annotations

from .. import llm
from ..models import Draft, Lead, Research

SYSTEM = """You write ONE plain-text, first-touch cold email built to earn a REPLY (not an open).
Write it TIGHT: 3-4 short sentences, ONE idea per sentence, no run-ons, no paragraph walls.
Every word must earn its place. If a sentence could be cut without losing meaning, cut it.

1) OPENER (1 sentence) — lead with EXACTLY ONE specific signal about THEM, named explicitly,
   drawn ONLY from FACTS: one recent event (expansion, new site, funding, news), OR one hiring
   signal, OR one regulatory/safety record (an OSHA citation/inspection, a crash/out-of-service
   trend), OR notable scale, OR a tool they use. Pick the SINGLE strongest — do NOT stack two or
   three facts into one sentence, that reads like a data dump. It must prove the email was written for THEM.
   BANNED openers: anything beyond "Hi <first>,"; "I hope this finds you well"; "I was on
   your website and noticed"; "As a <industry> company, you probably"; empty flattery.
2) BRIDGE (1 sentence) — tie THAT signal to a likely, CONCRETE challenge (PAIN as a hypothesis).
   Keep it specific to the signal and short, in plain real-world words.
   BANNED corporate filler / abstract noun pile-ups: "struggle to scale", "streamline processes",
   "leading to inefficiencies and inconsistent standards", "drive operational excellence",
   "at scale". Name the actual problem a person would recognize instead.
3) OUTCOME (1 sentence) — ONE plain-English line on the concrete change the product gives them —
   not a feature list, not a stack of abstract phrases.
   BANNED jargon strings like "custom mobile workflows to ensure consistent compliance across
   diverse operations without code" — pick ONE concrete outcome and say it simply.
   Add ONE short proof line ONLY IF a real proof point is in KNOWLEDGE — a quantified result
   ("<customer> cut X 40% in 30 days") OR a customer honestly attributed by role + industry
   ("a Director of Safety at a food manufacturer told us audit prep got much faster").
   If no proof is in KNOWLEDGE, omit it — NEVER invent a statistic, customer, or quote.
4) ASK (1 sentence) — ONE low-friction INTEREST QUESTION, never a meeting/time request. On a
   cold first touch an interest question earns roughly 2x the replies of a direct meeting ask,
   and calendar links / specific time-slot asks convert worst. It should be answerable with a
   one-word "yes". Good: "Worth a quick look?", "Is this on your radar this year?".
   BANNED: "book a demo", "click here to schedule", any "N-minute meeting/call", "hop on a call",
   any calendar link, any specific time proposal.

Format rules:
- SHORT and skimmable above all else — comfortably under the voice max_words, short sentences,
  one idea each. Plain text only: no markdown, no HTML, no bullet lists.
- State ONLY lead-specific facts present in FACTS. Pain stays a hypothesis. Invent nothing.
- Subject: 2-5 words, under ~40 characters, specific to THEM (their company/situation),
  lowercase fine. No first name in the subject, no clickbait, no question mark.
- Peer-to-peer, plain conversational English. At most one link, and never a calendar link.

Return STRICT JSON only:
{"subject": "...", "body": "...", "angle": "one line: why this lead", "used_facts": [fact indices you used]}"""

# A/B control variant: a competent personalized cold email that does NOT lead on a
# researched signal — so an experiment can isolate whether the grounded signal opener
# actually lifts replies. It gets NO facts block, only role/company/offer.
PLAIN_SYSTEM = """You write ONE plain-text, first-touch cold email built to earn a REPLY.
This is a CONTROL email: do NOT reference any specific researched fact about them
(no named events, citations, hires, numbers, tools, or news).
Write it TIGHT: 3-4 short sentences, ONE idea per sentence, no run-ons. Every word earns its place.

1) OPENER (1 sentence) — a relevant role/industry line ("Most safety leaders at growing
   carriers are juggling X"). Generic to their role/company, never a specific company fact.
2) BRIDGE (1 sentence) — the likely challenge as a hypothesis, in plain real-world words.
   BANNED corporate filler: "struggle to scale", "streamline processes", "leading to
   inefficiencies and inconsistent standards", "drive operational excellence", "at scale".
3) OUTCOME (1 sentence) — ONE plain, concrete outcome the product delivers, not a feature list
   or jargon string. A short proof line ONLY if one is in KNOWLEDGE.
4) ASK (1 sentence) — ONE low-friction INTEREST QUESTION, answerable with "yes". Never a
   meeting/time request, calendar link, or specific time.
   BANNED: "book a demo", "N-minute meeting/call", "hop on a call", any calendar link.

Format: SHORT and skimmable — short sentences, one idea each, under the voice max_words; plain
text (no markdown/HTML/bullets). Subject: 2-5 words, under ~40 chars, no first name, no question
mark. At most one link (never a calendar link). Invent nothing; any product claim must be in KNOWLEDGE.
Return STRICT JSON only:
{"subject": "...", "body": "...", "angle": "control (no signal opener)", "used_facts": []}"""


def signature_text(cfg: dict) -> str:
    """The email sign-off + sender footer, built deterministically from config.

    Kept OUT of the LLM body (so it never hallucinates a name/title/phone and stays
    identical on every send). Appended for display in Review and at send time.
    Returns '' when no sender.name is configured.
    """
    s = cfg.get("sender") or {}
    closing = (s.get("closing") or "").strip()
    # a verbatim signature block wins — lets you paste your exact plain-text sign-off
    raw = (s.get("signature") or "").strip()
    if raw:
        return f"{closing}\n{raw}" if closing else raw
    name = (s.get("name") or "").strip()
    if not name:
        return ""
    lines = [(closing or "Best,"), name]
    role = " · ".join(x for x in [(s.get("title") or "").strip(), (s.get("company") or "").strip()] if x)
    if role:
        lines.append(role)
    if s.get("phone"):
        lines.append(str(s["phone"]).strip())
    link = (s.get("link") or (cfg.get("offer") or {}).get("link") or "").strip()
    if link:
        lines.append(link)
    return "\n".join(lines)


def with_signature(body: str, cfg: dict) -> str:
    """Body with the sender footer appended (once). No-op if no sender configured."""
    sig = signature_text(cfg)
    return f"{body.rstrip()}\n\n{sig}" if sig else body


def _facts_block(research: Research) -> str:
    facts = "\n".join(
        f"[{i}] {f.claim}" + (f" ({f.published})" if f.published else "") + f"  <{f.source_type}>"
        for i, f in enumerate(research.facts)
    ) or "(none)"
    pains = "\n".join(
        f"- {p.hypothesis}  (from facts {p.supporting_facts})" for p in research.pain_points
    ) or "(none)"
    return f"FACTS:\n{facts}\n\nPAIN HYPOTHESES:\n{pains}"


def write_email(lead: Lead, research: Research, cfg: dict, variant: str = "signal"):
    """Returns (Draft, usage_dict, model_name).

    variant='signal' (default) = grounded, signal-led opener. variant='plain' = A/B
    control with no researched signal, to measure whether the signal opener lifts replies.
    """
    spec = llm.ModelSpec.from_config((cfg.get("models") or {}).get("personalize"))
    offer, voice = cfg["offer"], cfg["voice"]
    system = PLAIN_SYSTEM if variant == "plain" else SYSTEM
    # the control variant is deliberately NOT given the researched facts
    facts_line = "(control variant — no researched facts provided)" if variant == "plain" else _facts_block(research)
    user = f"""LEAD: {lead.full_name}, {lead.title} at {lead.company}

{facts_line}

OFFER: {offer.get('product')} — {offer.get('one_liner')}
VALUE PROPS: {offer.get('value_props')}
GOAL (what a reply should eventually lead toward — do NOT ask for it directly on this first touch; the ASK must stay a low-friction interest question): {offer.get('call_to_action')}
LINK (optional, at most one; never a calendar link): {offer.get('link')}
KNOWLEDGE (you may rely on these as true): {cfg.get('knowledge')}

VOICE: tone={voice.get('tone')}, max_words={voice.get('max_words')}
RULES: {voice.get('rules')}"""

    text, usage = llm.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        spec,
        temperature=0.7,
    )
    data = llm.parse_json(text)
    draft = Draft(
        subject=data.get("subject", ""),
        body=data.get("body", ""),
        angle=data.get("angle", ""),
        used_facts=data.get("used_facts") or [],
    )
    return draft, usage, spec.resolved_model()


REFINE_SYSTEM = """You revise an existing first-touch cold email per the user's INSTRUCTION,
while keeping it grounded and on-format.

Hard rules — NEVER break, even if the instruction implies otherwise:
- State ONLY lead-specific facts present in FACTS. Never invent a fact, statistic, customer, or quote.
- Plain text only — no markdown, HTML, or bullet lists. Keep it tight, a few short sentences.
- End with ONE low-friction interest question — never a demo/meeting ask, calendar link, or time.
- Subject: 2-5 words, under ~40 chars, no question mark.
- Do NOT add a sign-off or signature — that's appended automatically after this.

Apply the INSTRUCTION faithfully within those rules. If it asks for something that breaks a rule
(e.g. "ask for a meeting", "add a stat"), honor the intent but keep the rule (soft CTA; only real facts).

Return STRICT JSON only: {"subject": "...", "body": "..."}"""


def refine_email(lead: Lead, research: Research | None, cfg: dict, subject: str, body: str, instruction: str):
    """Rewrite an existing draft per a user instruction, staying grounded. Returns (Draft, usage, model)."""
    spec = llm.ModelSpec.from_config((cfg.get("models") or {}).get("personalize"))
    offer, voice = cfg["offer"], cfg["voice"]
    facts = _facts_block(research) if research else "FACTS:\n(none)"
    user = f"""LEAD: {lead.full_name}, {lead.title} at {lead.company}

CURRENT EMAIL
Subject: {subject}
Body:
{body}

{facts}

OFFER: {offer.get('product')} — {offer.get('one_liner')}
KNOWLEDGE (you may rely on these as true): {cfg.get('knowledge')}
VOICE: tone={voice.get('tone')}, max_words={voice.get('max_words')}

INSTRUCTION FROM THE USER: {instruction}"""

    text, usage = llm.complete(
        [{"role": "system", "content": REFINE_SYSTEM}, {"role": "user", "content": user}],
        spec,
        temperature=0.5,
    )
    data = llm.parse_json(text)
    draft = Draft(
        subject=data.get("subject") or subject,
        body=data.get("body") or body,
        angle=f"refined: {instruction[:80]}",
        used_facts=[],
    )
    return draft, usage, spec.resolved_model()
