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


def run_blast(store, bid: str, limit: int = 0) -> None:
    """Background worker: resolve the audience live, render per person, send in
    chunks, track per-recipient message ids for the webhook joins. Crash-safe:
    progress and status live on the blast doc; a failure pauses rather than lies.

    `limit` sends only that many of the people not yet mailed, so a list can be
    warmed in batches — five, read the bounces and complaints, then the rest. That
    is standard practice on a cold-ish list and the only way to find a deliverability
    problem while it still costs five addresses instead of two hundred. Recipients
    already sent are skipped, so 'send the rest' continues rather than duplicating.
    """
    blast = store.get_blast(bid)
    if not blast:
        return
    try:
        pub = store.get_publication(blast.get("publication_id", "")) or {}
        # An issue number is claimed once, on the first batch — warming a list in
        # five-person batches must not produce issues #4, #5 and #6 of the same email.
        if pub and not blast.get("issue_no"):
            issue = store.next_issue_no(pub["_id"])
            store.update_blast(bid, {"issue_no": issue})
            blast["issue_no"] = issue
        everyone = store.audience_leads(blast.get("audience") or {})
        already = store.blast_sent_emails(bid)
        pending = [p for p in everyone if p["email"] not in already]
        people = pending[:limit] if limit and limit > 0 else pending
        total = len(people)
        remaining_after = len(pending) - total
        store.update_blast(bid, {"status": "sending",
                                 "stats.recipients": len(already) + total,
                                 "audience_size": len(everyone),
                                 "progress": {"done": 0, "total": total}})
        done = 0
        for i in range(0, total, CHUNK):
            chunk = people[i:i + CHUNK]
            msgs = []
            for p in chunk:
                m = render_message(blast, p["lead"], p["email"])
                # A publication can send under its own name and take its own replies —
                # "The Safety Brief" and "Freight Paperwork" should not look like the
                # same mailing list to someone subscribed to one of them.
                if pub.get("from_address"):
                    m["from"] = pub["from_address"]
                if pub.get("reply_to"):
                    m["reply_to"] = pub["reply_to"]
                msgs.append(m)
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
        # 'partial' is a real state, not a failure: the batch went, more are waiting.
        # Calling it 'sent' would hide that two hundred people never got it.
        store.update_blast(bid, {
            "status": "partial" if remaining_after > 0 else "sent",
            "remaining": remaining_after,
            "sent_at": datetime.now(timezone.utc).isoformat()})
    except Exception as e:
        log.warning("[blast %s] paused: %s", bid, e)
        store.update_blast(bid, {"status": "paused", "error": f"{type(e).__name__}: {e}"[:400]})
