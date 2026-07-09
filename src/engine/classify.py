"""Reply classification — label inbound replies so the product can act on them.

Labels:
  interested      — positive engagement: wants info, a call, asks questions, "sounds good"
  not_interested  — a real human politely declining ("we're all set", "not for us")
  opt_out         — asks to stop / unsubscribe / remove ("no thanks", "take me off your list")
  ooo             — auto-reply: out of office, vacation, parental leave, auto-acknowledgement
  other           — bounces disguised as replies, unclear, forwarding notices, anything else

opt_out feeds the do-not-contact list automatically; interested is the metric that
matters (positive replies). Classification is mechanical → cheap fast model, cached
per message id by the caller.
"""
from __future__ import annotations

from .. import llm

LABELS = {"interested", "not_interested", "opt_out", "ooo", "other"}

SYSTEM = """You label ONE reply to a B2B cold email. Return exactly one label:

- interested: positive engagement — asks a question about the product, wants a call/demo/
  more info, "sounds interesting", refers you to the right colleague WITH engagement.
- not_interested: a human declining without asking to be removed — "we're all set",
  "no budget", "not a priority", "we use a competitor".
- opt_out: any request to stop contacting — "no thanks", "unsubscribe", "remove me",
  "stop emailing", "not interested, don't contact again", legal threats.
- ooo: automatic replies — out of office, vacation, no longer with the company,
  auto-acknowledgements.
- other: bounce notices, empty/unclear, pure forwards, anything that fits nothing above.

Edge rule: "not interested" + any stop/remove request = opt_out (the stop request wins).

Return STRICT JSON only: {"label": "..."}"""


def classify_reply(text: str, cfg: dict | None = None) -> str:
    """Label one reply body. Returns a LABELS member ('other' on any failure)."""
    body = (text or "").strip()
    if not body:
        return "other"
    spec = llm.ModelSpec.from_config(((cfg or {}).get("models") or {}).get("classify"))
    try:
        out, _usage = llm.complete(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": body[:4000]}],
            spec,
            temperature=0.0,
        )
        label = (llm.parse_json(out).get("label") or "").strip().lower()
        return label if label in LABELS else "other"
    except Exception:
        return "other"
