"""Marketing engine — blasts (newsletters/announcements) from the Library via Postmark.

One message, one human approval, many recipients — the counterpart to the sales
engine's one-lead-at-a-time review. Everything is rendered HERE (merge fields via
the same deterministic fill_placeholders that verbatim sales mail uses); Postmark
is the pipe, on its broadcast stream, fully separate from the sales mailboxes.

Compliance is built into the render, not optional: every message carries a footer
with a per-recipient one-click unsubscribe (HMAC-signed, straight onto the global
do-not-contact list) and a List-Unsubscribe header.
"""
from __future__ import annotations

import html as html_mod
import logging
from datetime import datetime, timezone

from .engine.personalize import fill_placeholders
from .integrations import postmark_send
from .unsubscribe import link as unsub_link

log = logging.getLogger("uvicorn.error")

FOOTER_TEXT = ("\n\n—\nYou're receiving this because you've been in touch with Knowella.\n"
               "Unsubscribe: {url}")
CHUNK = 100   # render+send in small chunks so progress moves and one failure loses little


def render_message(blast: dict, lead, email: str) -> dict:
    """One fully-rendered Postmark message for one person: merge fields filled,
    unsubscribe footer + header attached, text + minimal HTML (for open/click
    tracking) generated from the same body."""
    url = unsub_link(email)
    subject = fill_placeholders(blast["subject"], lead, {})
    body = fill_placeholders(blast["body"], lead, {})
    text = body + FOOTER_TEXT.format(url=url)
    paras = "".join(f"<p>{html_mod.escape(p).replace(chr(10), '<br>')}</p>"
                    for p in body.split("\n\n") if p.strip())
    html = (f'<div style="font-family:Poppins,Arial,sans-serif;font-size:14px;'
            f'line-height:1.6;color:#242a32;max-width:600px">{paras}'
            f'<p style="color:#96a5b5;font-size:12px;border-top:1px solid #e6ecf1;'
            f'padding-top:12px;margin-top:24px">You\'re receiving this because you\'ve been '
            f'in touch with Knowella. <a href="{url}" style="color:#6e63ff">Unsubscribe</a></p></div>')
    return {
        "to": email,
        "subject": subject,
        "text_body": text,
        "html_body": html,
        "headers": {"List-Unsubscribe": f"<{url}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
        "metadata": {"blast_id": blast["_id"], "email": email},
    }


def run_blast(store, bid: str) -> None:
    """Background worker: resolve the audience live, render per person, send in
    chunks, track per-recipient message ids for the webhook joins. Crash-safe:
    progress and status live on the blast doc; a failure pauses rather than lies."""
    blast = store.get_blast(bid)
    if not blast:
        return
    try:
        people = store.audience_leads(blast.get("audience") or {})
        total = len(people)
        store.update_blast(bid, {"status": "sending", "stats.recipients": total,
                                 "progress": {"done": 0, "total": total}})
        done = 0
        for i in range(0, total, CHUNK):
            chunk = people[i:i + CHUNK]
            msgs = [render_message(blast, p["lead"], p["email"]) for p in chunk]
            results = postmark_send.send_batch(msgs)
            for p, res in zip(chunk, results):
                ok = not res.get("ErrorCode")
                store.add_blast_recipient(bid, p["email"], p["key"],
                                          res.get("MessageID", ""), ok)
                store.inc_blast_stat(bid, "accepted" if ok else "failed")
                if not ok:
                    log.warning("[blast %s] %s rejected: %s", bid, p["email"], res.get("Message"))
            done += len(chunk)
            store.update_blast(bid, {"progress": {"done": done, "total": total}})
        store.update_blast(bid, {"status": "sent",
                                 "sent_at": datetime.now(timezone.utc).isoformat()})
    except Exception as e:
        log.warning("[blast %s] paused: %s", bid, e)
        store.update_blast(bid, {"status": "paused", "error": f"{type(e).__name__}: {e}"[:400]})
