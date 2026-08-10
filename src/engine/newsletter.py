"""Draft a newsletter issue — bounded by what the publication may actually claim.

The sales writer is grounded by researched facts about one lead. A newsletter has
no single lead, so the grounding is the publication's KNOWLEDGE block: the only
statements it may present as true. Everything else it must either attribute to a
named public source (an OSHA release, a rule change) or leave out.

That constraint is not decoration. The whole product argues that every sentence
has a source; a generator that invents "teams save 40% of admin time" to fill a
paragraph would refute the pitch on the company's own mailing list.

Inputs, best first:
  question   a Backlog item — something a real buyer actually asked. The strongest
             brief there is, because it guarantees the issue answers a live question
             rather than announcing something nobody wondered about.
  signal     an optional dated public event (an OSHA citation, a rule change) that
             gives the issue a reason to exist THIS week.
  audience   who it is going to, so it writes to safety directors at carriers
             rather than to "business leaders".
"""
from __future__ import annotations

from .. import llm

SYSTEM = (
    "You write a short B2B email newsletter issue for a specialist audience. "
    "You are strictly bounded by the KNOWLEDGE block: it is the only thing you may "
    "state as fact about the product. You may also reference a SIGNAL, which is a "
    "real dated public event, and you must attribute it plainly.\n\n"
    "Absolute rules:\n"
    "- Invent NOTHING. No statistics, percentages, customer names, case studies, "
    "time savings or ROI figures unless they appear verbatim in KNOWLEDGE.\n"
    "- If you cannot make a point without a number you do not have, make the point "
    "without the number or drop the point.\n"
    "- Obey every 'DO NOT claim' line in KNOWLEDGE exactly.\n"
    "- The issue must be worth reading by someone who will never buy anything. It "
    "carries at least one thing they can go and do, or check, or stop doing, using "
    "only what they already have. If everything in it depends on owning the product, "
    "you have written an advertisement — start again.\n"
    "- Open on the reader's situation, not on the category. 'Streamlining Multi-Method "
    "Ergonomic Assessments' is a whitepaper title; 'Your REBA scores disagree with "
    "your incident log' is a newsletter.\n"
    "- The product may appear ONCE, in the last paragraph, and only if it genuinely "
    "answers the question. Never describe its features in sequence — a list of "
    "capabilities in prose is still a feature list.\n"
    "- Banned openers: 'Dear'. Use a plain salutation or none.\n"
    "- Banned in the subject: Streamlining, Leveraging, Enhancing, Optimizing, "
    "Unlocking, Navigating, Comprehensive, Robust, Solutions. Write what a "
    "practitioner would actually click.\n"
    "- No 'I hope this finds you well', no exclamation marks, no em-dash pile-ups, "
    "no invented urgency.\n"
    "- Merge fields available: {first_name}, {company}, {title}. Use {first_name} "
    "at most once and only if it reads naturally.\n"
    "- Formatting is markdown, and only three marks exist: **bold** (once per issue "
    "at most, for the term being named), '- ' bullets (one short list per issue at "
    "most, and only where the content is genuinely a list), and [text](url) links.\n"
    "- NEVER invent a URL. Link only to an address that appears verbatim in the "
    "SIGNAL or KNOWLEDGE above. A fabricated source is worse than no source, and on "
    "this list it would be self-refuting. If you have no URL, name the source in "
    "words and leave it unlinked.\n"
    "- The unsubscribe footer is added automatically; do not write one.\n\n"
    'Return ONLY JSON: {"subject": str, "body": str, "used": [str], "omitted": [str]}\n'
    '"used" lists the KNOWLEDGE or SIGNAL points you actually leaned on.\n'
    '"omitted" lists ONLY points you WANTED to make but could not, because you had no '
    "source for them. Do NOT list the DO NOT rules — obeying those is expected, not an "
    "omission. Do NOT list knowledge points that were simply irrelevant to this issue. "
    "If nothing was genuinely held back, return an empty list."
)


QUESTION_SYSTEM = (
    "You propose questions a real practitioner would actually ask — the kind typed "
    "into a forum at 6pm after something went wrong, not headings from a brochure.\n"
    "Rules:\n"
    "- Each must be answerable using the KNOWLEDGE given, at least partly.\n"
    "- Written in the practitioner's words, about their problem, never naming the "
    "product. 'Why do our sites fail audits when the training actually happened?' "
    "not 'How can software improve training compliance?'\n"
    "- Specific enough that a generic answer would be obviously useless.\n"
    '- Return ONLY JSON: {"questions": [str, str, str, str]}'
)


def suggest_questions(pub: dict, spec_cfg: dict | None = None) -> list[str]:
    """Four questions this publication could answer.

    A stopgap, and worth being honest about: the real questions come from buyers,
    via the Backlog. These are guesses made from the product knowledge, which is the
    same trap as writing content about what you sell rather than what people ask.
    Useful while the Backlog is empty; not a replacement for it.
    """
    user = f"""PUBLICATION: {pub.get('name')} — {pub.get('description') or ''}
AUDIENCE: {pub.get('description') or 'EHS and safety leaders at industrial employers'}

KNOWLEDGE:
{pub.get('knowledge') or '(none)'}"""
    spec = llm.ModelSpec.from_config(spec_cfg or {})
    text, _ = llm.complete(
        [{"role": "system", "content": QUESTION_SYSTEM}, {"role": "user", "content": user}],
        spec, temperature=0.9,
    )
    qs = llm.parse_json(text).get("questions") or []
    return [q.strip() for q in qs if isinstance(q, str) and q.strip()][:4]


def write_issue(pub: dict, question: str = "", signal: dict | None = None,
                audience_hint: str = "", spec_cfg: dict | None = None) -> dict:
    """One issue → {subject, body, used, omitted}. Raises on an unusable response."""
    sig = ""
    if signal:
        bits = [signal.get("company"), signal.get("title"), signal.get("text")]
        where = signal.get("url") or ""
        sig = " · ".join(b for b in bits if b) + (f" (source: {where})" if where else "")

    user = f"""PUBLICATION: {pub.get('name')} — {pub.get('description') or ''}
PRODUCT: {pub.get('product')}
VOICE: {pub.get('voice') or 'plain, practical, no hype'}

AUDIENCE: {audience_hint or 'EHS and safety leaders at industrial employers'}

KNOWLEDGE (the ONLY product claims you may state as fact):
{pub.get('knowledge') or '(none supplied — do not make any product claim at all)'}

QUESTION THIS ISSUE ANSWERS: {question or '(none given — pick one useful, concrete angle from the knowledge above and answer it)'}

SIGNAL (a real dated public event you may reference and attribute): {sig or '(none)'}

Write the issue. 150-250 words in the body."""

    spec = llm.ModelSpec.from_config(spec_cfg or {})
    text, _usage = llm.complete(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        spec, temperature=0.6,
    )
    data = llm.parse_json(text)
    if not data.get("subject") or not data.get("body"):
        raise RuntimeError("the model returned no subject or body")
    return {"subject": data.get("subject", "").strip(),
            "body": data.get("body", "").strip(),
            "used": data.get("used") or [],
            "omitted": data.get("omitted") or []}
