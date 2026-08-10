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
    "- This is a newsletter, not a pitch. Be useful first; mention the product only "
    "where it genuinely answers the question, and at most once.\n"
    "- No greeting beyond a short salutation, no 'I hope this finds you well', no "
    "exclamation marks, no em-dash pile-ups, no invented urgency.\n"
    "- Merge fields available: {first_name}, {company}, {title}. Use {first_name} "
    "at most once and only if it reads naturally.\n"
    "- The unsubscribe footer is added automatically; do not write one.\n\n"
    'Return ONLY JSON: {"subject": str, "body": str, "used": [str], "omitted": [str]}\n'
    '"used" lists the KNOWLEDGE or SIGNAL points you actually leaned on.\n'
    '"omitted" lists ONLY points you WANTED to make but could not, because you had no '
    "source for them. Do NOT list the DO NOT rules — obeying those is expected, not an "
    "omission. Do NOT list knowledge points that were simply irrelevant to this issue. "
    "If nothing was genuinely held back, return an empty list."
)


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
