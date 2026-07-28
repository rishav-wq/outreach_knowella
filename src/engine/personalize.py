"""Stage 2 — turn cited facts into a grounded, relevant email.

The model may ONLY state lead-specific facts that appear in FACTS. Pain points are
passed as hypotheses and must stay hypotheses. The quality gate verifies compliance
afterward — this stage just produces the best grounded draft it can.
"""
from __future__ import annotations

import re

from .. import llm
from ..models import Draft, Lead, Research


# --- deterministic style enforcement -----------------------------------------
# LLMs won't reliably follow "no em-dashes" or a subject-length rule no matter how
# the prompt is worded (and our own prompt is full of em-dashes, which primes them).
# So we GUARANTEE these mechanical rules in code, on every generated draft/follow-up.
def clean_dashes(text: str) -> str:
    """Replace em/en dashes with a plain hyphen — kills the #1 'this is AI' tell and
    honors 'no long hyphens'. Safe for number ranges (10–20 → 10-20)."""
    if not text:
        return text
    return text.replace("—", "-").replace("–", "-").replace(" - ", " - ")


def clean_subject(subject: str, max_chars: int = 52) -> str:
    """Dash-clean + hard length cap (trim to the last whole word) so subjects stay
    short even when the model ignores the 'under ~40 chars' instruction."""
    s = clean_dashes(subject or "").strip().strip(".")
    if len(s) > max_chars:
        s = s[:max_chars].rsplit(" ", 1)[0].rstrip(" ,-")
    return s

SYSTEM = """You write ONE plain-text, first-touch cold email built to earn a REPLY (not an open).
Write it TIGHT: 3-4 short sentences, ONE idea per sentence, no run-ons, no paragraph walls.
Every word must earn its place. If a sentence could be cut without losing meaning, cut it.

1) OPENER (1 sentence) — lead with EXACTLY ONE specific signal about THEM, named explicitly,
   drawn ONLY from FACTS: one recent event (expansion, new site, funding, news), OR one hiring
   signal, OR one regulatory/safety record (an OSHA citation/inspection, a crash/out-of-service
   trend), OR notable scale, OR a tool they use. Pick the SINGLE strongest — do NOT stack two or
   three facts into one sentence, that reads like a data dump. It must prove the email was written for THEM.
   NAME THE SPECIFICS: carry the fact's concrete anchor into the sentence — the place, number,
   role, or named thing ("hiring Class A CDL drivers", "the new Dover, Ohio complex", "13
   terminals across Idaho"). BANNED vague compressions: "is actively expanding", "is growing",
   "has been making changes", "recently expanded" or ANY paraphrase that names no specific —
   if the best fact has no concrete anchor, use the strongest one that does.
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
- LAYOUT (hard rule): ONE sentence per line, with a BLANK line between every sentence/paragraph.
  Cold email is read on a phone — a dense block of run-together sentences kills replies. Never
  produce a paragraph of more than 2 short sentences.
- State ONLY lead-specific facts present in FACTS. Pain stays a hypothesis. Invent nothing.
- Subject: 2-5 words, under ~40 characters, specific to THEM (their company/situation),
  lowercase fine. No first name in the subject, no clickbait, no question mark.
- No em-dashes or en-dashes anywhere; use a comma or a short hyphen instead.
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

Format: SHORT and skimmable, short sentences, one idea each, under the voice max_words; plain
text (no markdown/HTML/bullets). LAYOUT (hard rule): ONE sentence per line with a BLANK line
between each, never a dense block. Subject: 2-5 words, under ~40 chars, no first name, no question
mark. No em-dashes or en-dashes anywhere; use a comma or a short hyphen. At most one link (never a
calendar link). Invent nothing; any product claim must be in KNOWLEDGE.
Return STRICT JSON only:
{"subject": "...", "body": "...", "angle": "control (no signal opener)", "used_facts": []}"""


def signature_text(cfg: dict, lead: Lead | None = None) -> str:
    """The email sign-off + sender footer, built deterministically from config.

    Kept OUT of the LLM body (so it never hallucinates a name/title/phone and stays
    identical on every send). Appended for display in Review and at send time.
    Returns '' when no sender.name is configured. When `lead` (with an email) is given,
    the opt-out becomes a ONE-CLICK unsubscribe LINK; otherwise (e.g. Review preview)
    a placeholder notes the link is added at send.
    """
    from ..unsubscribe import link as unsub_link
    s = cfg.get("sender") or {}
    closing = (s.get("closing") or "").strip()
    # compliance: a one-click unsubscribe after the sign-off (lower friction than
    # "reply no thanks", and what mailbox providers now expect). Honoring it is
    # enforced by the do-not-contact list (suppression) at pull/pipeline/send.
    if lead and lead.email:
        opt_out = f"Not the right fit? Unsubscribe: {unsub_link(lead.email)}"
    else:
        opt_out = "Not the right fit? Unsubscribe: [one-click link added when sent]"
    # When the sending platform appends its own signature (e.g. an Apollo mailbox
    # signature), skip our sender block so the email isn't signed twice — emit ONLY
    # the unsubscribe line. The platform's signature is the sign-off; compliance
    # (one-click unsubscribe) still rides along.
    if (cfg.get("sending") or {}).get("use_mailbox_signature"):
        return opt_out
    tail = f"\n\n{opt_out}"
    # a verbatim signature block wins — lets you paste your exact plain-text sign-off
    raw = (s.get("signature") or "").strip()
    if raw:
        return (f"{closing}\n{raw}" if closing else raw) + tail
    name = (s.get("name") or "").strip()
    if not name:
        return opt_out   # no sender block, but still include the unsubscribe line
    lines = [(closing or "Best,"), name]
    role = " · ".join(x for x in [(s.get("title") or "").strip(), (s.get("company") or "").strip()] if x)
    if role:
        lines.append(role)
    if s.get("phone"):
        lines.append(str(s["phone"]).strip())
    link = (s.get("link") or (cfg.get("offer") or {}).get("link") or "").strip()
    if link:
        lines.append(link)
    return "\n".join(lines) + tail


def with_signature(body: str, cfg: dict, lead: Lead | None = None) -> str:
    """Body with the sender footer + per-lead unsubscribe link appended (once)."""
    sig = signature_text(cfg, lead)
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


VERBATIM_SYSTEM = """The user wrote the TEMPLATE below and wants it sent almost exactly as-is —
keep AT LEAST 90% of their wording, sentences, and order. Reproduce it faithfully.

Your ONLY edits:
- Replace placeholders (e.g. [first name], {first_name}, [company], {company}, [role]) with this
  lead's real details. If a placeholder has no value, remove it cleanly.
- Fix only broken grammar or spacing.

Do NOT rewrite, reorder, shorten, add, or remove sentences. Do NOT add facts, claims, or a
signature. Plain text only. No em-dashes or en-dashes.
Return STRICT JSON only: {"subject": "...", "body": "...", "angle": "verbatim template", "used_facts": []}"""


def _write_verbatim(lead: Lead, cfg: dict, template: str, subject: str, spec):
    """'Use AI' is OFF: send the user's template near-verbatim, just filling placeholders.
    Low temperature so it stays faithful to their copy."""
    user = (f"LEAD: {lead.full_name}, {lead.title} at {lead.company}\n\n"
            f"TEMPLATE (reproduce this):\n{template}\n\n"
            f"SUBJECT: {subject or '(none given — write a short 2-5 word subject that fits)'}")
    text, usage = llm.complete(
        [{"role": "system", "content": VERBATIM_SYSTEM}, {"role": "user", "content": user}],
        spec, temperature=0.15)
    data = llm.parse_json(text)
    draft = Draft(body=clean_dashes(data.get("body", "")),
                  subject=clean_dashes(subject) if subject else clean_subject(data.get("subject", "")),
                  angle="verbatim template", used_facts=[])
    return draft, usage, spec.resolved_model()


def write_email(lead: Lead, research: Research, cfg: dict, variant: str = "signal"):
    """Returns (Draft, usage_dict, model_name).

    variant='signal' (default) = grounded, signal-led opener. variant='plain' = A/B
    control with no researched signal, to measure whether the signal opener lifts replies.
    When the campaign's sequence has use_ai=False and step 1 has a template, the user's
    copy is reproduced near-verbatim instead (see _write_verbatim).
    """
    spec = llm.ModelSpec.from_config((cfg.get("models") or {}).get("personalize"))
    offer, voice = cfg["offer"], cfg["voice"]
    system = PLAIN_SYSTEM if variant == "plain" else SYSTEM
    # the control variant is deliberately NOT given the researched facts
    facts_line = "(control variant — no researched facts provided)" if variant == "plain" else _facts_block(research)
    # optional user-pasted template for the first email (sequence step 1) — steers
    # structure/length/voice; the facts stay lead-specific and all hard rules still apply
    seq_steps = (cfg.get("sequence") or {}).get("steps") or []
    tmpl = (seq_steps[0].get("template") or "").strip() if seq_steps else ""
    # "Use AI" OFF + a template supplied → reproduce the user's copy near-verbatim.
    if not (cfg.get("sequence") or {}).get("use_ai", True) and tmpl:
        return _write_verbatim(lead, cfg, tmpl, (seq_steps[0].get("subject") or "").strip(), spec)
    tmpl_block = (f"""
TEMPLATE (mirror its structure, length, and voice — but replace every [bracketed placeholder]
and example-specific detail with THIS lead's specifics; copying template examples verbatim is
a hard failure; all rules above still apply):
---
{tmpl}
---
""" if tmpl else "")
    user = f"""LEAD: {lead.full_name}, {lead.title} at {lead.company}

{facts_line}
{tmpl_block}
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
    # a user-set subject for step 1 wins verbatim over the AI's — the campaign
    # owner controls the subject line when they choose to (empty = AI writes it).
    fixed_subject = (seq_steps[0].get("subject") or "").strip() if seq_steps else ""
    # deterministic style: strip em/en dashes everywhere; cap AI subject length
    # (a user-set subject is respected as-is, only dash-cleaned).
    draft.body = clean_dashes(draft.body)
    draft.subject = clean_dashes(fixed_subject) if fixed_subject else clean_subject(draft.subject)
    return draft, usage, spec.resolved_model()


FOLLOWUP_SYSTEM = """You write the follow-up emails for a cold outreach sequence. The lead
already received the FIRST EMAIL below and did not reply. Same hard rules as the first email:
plain text only, ONLY facts present in FACTS, invent nothing, no sign-off/signature (appended
automatically), each ends with ONE low-friction interest question — never a meeting ask,
calendar link, or time proposal.

You'll be given one brief PER follow-up, in send order. Each brief either includes a TEMPLATE
or says "(no template)":
- With a TEMPLATE: mirror its structure, length, and voice — but replace every [bracketed
  placeholder] and every example-specific detail with THIS lead's specifics from FACTS/OFFER.
  Template examples belong to someone else; copying them verbatim is a hard failure.
- Without a template, defaults by position: the first follow-up is a short, polite bump
  (2-3 short sentences: "wanted to float this back up", ONE fresh value line that does not
  repeat the first email's opener fact or phrasing, soft question; no guilt-tripping). Each
  later follow-up takes a NEW ANGLE — lead with a different usable fact from FACTS, or a
  different pain/outcome. The final one may read as a calm last note — no pressure, no
  "final attempt" drama.
Every follow-up must differ from the first email AND from each other — never reuse an opener
fact or phrasing across steps.

LAYOUT (hard rule, all of them): ONE sentence per line with a BLANK line between each —
read on a phone, never a dense block.

Return STRICT JSON only: {"followups": ["<body of follow-up 1>", "<body of follow-up 2>", ...]}
— exactly one entry per brief, in order."""


def write_followups(lead: Lead, research: Research | None, cfg: dict, first_subject: str,
                    first_body: str, steps: list[dict], variant: str = "signal"):
    """Bodies for every follow-up step (sequence steps 2..N), any count.

    steps = [{'wait_days': int, 'template': str}] per follow-up, in send order — the
    template ('' for none) steers that step's structure/voice while facts stay
    lead-specific. Returns (bodies: list[str], usage, model). Subjects are derived
    deterministically ('Re: <first subject>') so the thread reads continuous.
    """
    spec = llm.ModelSpec.from_config((cfg.get("models") or {}).get("personalize"))
    offer, voice = cfg["offer"], cfg["voice"]
    use_ai = (cfg.get("sequence") or {}).get("use_ai", True)
    facts = ("(control variant — no researched facts; keep all follow-ups role-based and generic)"
             if variant == "plain" else (_facts_block(research) if research else "FACTS:\n(none)"))
    briefs = []
    for i, st in enumerate(steps):
        tmpl = (st.get("template") or "").strip()
        head = f"FOLLOW-UP {i + 1} of {len(steps)} (sends ~{st.get('wait_days') or 3} days after the previous email):"
        briefs.append(f"{head}\nTEMPLATE:\n---\n{tmpl}\n---" if tmpl else f"{head} (no template)")
    # "Use AI" OFF: reproduce any templated follow-up near-verbatim (fill placeholders only).
    verbatim_note = ("" if use_ai else
                     "\nIMPORTANT — 'Use AI' is OFF: for any follow-up that HAS a template, reproduce it "
                     "near-verbatim (keep at least 90% of the wording, only fill placeholders, do not rewrite).\n")
    user = f"""LEAD: {lead.full_name}, {lead.title} at {lead.company}{verbatim_note}

FIRST EMAIL (already sent, no reply)
Subject: {first_subject}
Body:
{first_body}

{facts}

{chr(10).join(briefs)}

OFFER: {offer.get('product')} — {offer.get('one_liner')}
VALUE PROPS: {offer.get('value_props')}
KNOWLEDGE (you may rely on these as true): {cfg.get('knowledge')}
VOICE: tone={voice.get('tone')}, max_words={voice.get('max_words')}"""

    text, usage = llm.complete(
        [{"role": "system", "content": FOLLOWUP_SYSTEM}, {"role": "user", "content": user}],
        spec,
        temperature=0.6,
    )
    data = llm.parse_json(text)
    bodies = [clean_dashes(str(b or "")) for b in (data.get("followups") or [])]
    bodies += [""] * (len(steps) - len(bodies))   # never shorter than asked
    return bodies[:len(steps)], usage, spec.resolved_model()


REFINE_SYSTEM = """You revise an existing first-touch cold email per the user's INSTRUCTION,
while keeping it grounded and on-format.

Hard rules — NEVER break, even if the instruction implies otherwise:
- State ONLY lead-specific facts present in FACTS. Never invent a fact, statistic, customer, or quote.
- Plain text only — no markdown, HTML, or bullet lists. Keep it tight, a few short sentences.
- LAYOUT: ONE sentence per line with a blank line between each — never a dense paragraph block.
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
        subject=clean_subject(data.get("subject") or subject),
        body=clean_dashes(data.get("body") or body),
        angle=f"refined: {instruction[:80]}",
        used_facts=[],
    )
    return draft, usage, spec.resolved_model()
