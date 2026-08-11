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
import re
from datetime import datetime, timezone

from .engine.personalize import fill_placeholders
from .integrations import postmark_send

log = logging.getLogger("uvicorn.error")

# Postmark appends its OWN unsubscribe link to every broadcast message unless the
# body contains this placeholder — which is why the first test arrived with two.
# Handing it the placeholder means one link, and it is the better one to keep:
# Postmark implements RFC 8058 one-click for broadcast streams (what Gmail and
# Yahoo now require of bulk senders) and suppresses the address at the stream.
# It reaches our own do-not-contact list through the SubscriptionChange webhook,
# which suppresses globally and cancels pending sequence mail — so an unsubscribe
# still stops sales, not just this newsletter.
PM_UNSUB = "{{{ pm:unsubscribe }}}"
FOOTER_TEXT = ("\n\n—\nYou're receiving this because you've been in touch with Knowella.\n"
               "Unsubscribe: " + PM_UNSUB)
CHUNK = 100   # render+send in small chunks so progress moves and one failure loses little

# One body, two renderings. The composer stays plain text — the format that wins for
# B2B and the one a person can actually read back before approving it — so the small
# amount of structure a newsletter genuinely needs is written as markdown and degrades
# to something readable in the text part. Deliberately three things and no more:
#
#   links    the whole product argues every claim has a source. A cited OSHA release
#            that isn't clickable in the HTML part is the one omission we can't make.
#   bullets  an EHS checklist is a list. Prose-ifying it helps nobody.
#   bold     one term per issue, for the thing being named.
#
# No headings, images, buttons, columns or colours. Those are what make a newsletter
# look like bulk mail, and looking like bulk mail is what costs opens.
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)|(https?://[^\s<]+)")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_BULLET = re.compile(r"^\s*[-*]\s+")


def _inline(t: str) -> str:
    """Escaped text → links and bold. Escaping first means a body can contain < or &
    without breaking the message, and URLs keep working because &amp; is what an href
    is supposed to carry anyway."""
    def link(m):
        if m.group(2):
            return f'<a href="{m.group(2)}" style="color:#6e63ff">{m.group(1)}</a>'
        url = m.group(3).rstrip(".,;:!?)")   # sentence punctuation is not part of the URL
        tail = m.group(3)[len(url):]
        return f'<a href="{url}" style="color:#6e63ff">{url}</a>{tail}'
    out = _MD_LINK.sub(link, html_mod.escape(t))
    return _MD_BOLD.sub(r"<strong>\1</strong>", out)


_P = 'style="margin:0 0 18px"'


def to_html(body: str) -> str:
    """Body → paragraphs and lists.

    Runs of bullet lines become a list wherever they appear, including directly
    under the sentence introducing them. Requiring a whole block to be bullets was
    wrong in the most common case there is — 'here is the check:' followed by the
    check — and turned every list into a paragraph of literal hyphens, which is
    what made a short issue read as a wall.
    """
    out, run = [], []

    def flush_list():
        if run:
            items = "".join(f'<li style="margin-bottom:6px">{_inline(x)}</li>' for x in run)
            out.append(f'<ul style="margin:0 0 18px;padding-left:22px">{items}</ul>')
            run.clear()

    for block in body.split("\n\n"):
        para = []
        for ln in (l for l in block.split("\n") if l.strip()):
            if _BULLET.match(ln):
                if para:
                    out.append(f'<p {_P}>{"<br>".join(para)}</p>')
                    para = []
                run.append(_inline(_BULLET.sub("", ln)))
            else:
                flush_list()
                para.append(_inline(ln))
        if para:
            out.append(f'<p {_P}>{"<br>".join(para)}</p>')
        flush_list()
    return "".join(out)


def to_text(body: str) -> str:
    """Body → plain text. Bold markers go (they read as noise unformatted) and a
    markdown link becomes 'text (url)' so the address is still there to copy."""
    t = _MD_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})" if m.group(2) else m.group(3), body)
    return _MD_BOLD.sub(r"\1", t)


_TAGS = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_BREAKS = re.compile(r"(?i)</(p|div|tr|h[1-6]|li)>|<br\s*/?>")


def html_to_text(h: str) -> str:
    """A readable plain-text part for a body written as HTML.

    Every message still ships both parts: a text/plain alternative is one of the
    oldest things spam filters look for, and some recipients genuinely read it. The
    author writing HTML is not a reason to send an empty or tag-stuffed text body.
    """
    s = _TAGS.sub(" ", h or "")
    s = _BREAKS.sub("\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def render_message(blast: dict, lead, email: str) -> dict:
    """One fully-rendered Postmark message for one person: merge fields filled,
    unsubscribe footer + header attached, text + HTML generated from the same body.

    `format` is 'markdown' (default) or 'html'. In html the body is used verbatim,
    for the times a hand-built or designer-supplied block is genuinely needed. What
    it does NOT bypass is the footer: the unsubscribe placeholder is appended in
    both modes, because Postmark appends its own to any broadcast message lacking
    it and the result would be two links again.
    """
    subject = fill_placeholders(blast["subject"], lead, {})
    body = fill_placeholders(blast["body"], lead, {})
    raw = (blast.get("format") or "markdown") == "html"
    text = (html_to_text(body) if raw else to_text(body)) + FOOTER_TEXT
    # 15px/1.7 over a 560px measure: ~70 characters a line, the range typography
    # research keeps landing on for sustained reading. 14px over 600px ran nearer 85,
    # which is where the eye starts losing its place on the return sweep — a slower
    # read that gets blamed on length.
    html = (f'<div style="font-family:Poppins,Arial,sans-serif;font-size:15px;'
            f'line-height:1.7;color:#242a32;max-width:560px">{body if raw else to_html(body)}'
            f'<p style="color:#96a5b5;font-size:12px;border-top:1px solid #e6ecf1;'
            f'padding-top:12px;margin-top:8px">You\'re receiving this because you\'ve been '
            f'in touch with Knowella. <a href="{PM_UNSUB}" style="color:#6e63ff">Unsubscribe</a></p></div>')
    return {
        "to": email,
        "subject": subject,
        "text_body": text,
        "html_body": html,
        # No List-Unsubscribe header here: Postmark writes its own for broadcast
        # streams, and ours pointed somewhere different, which would have given
        # mailbox providers two conflicting one-click targets for one message.
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
