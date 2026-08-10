"""Marketing email — Postmark.

The MARKETING engine's pipe (1:many blasts/newsletters), deliberately separate
from the sales engine (Apollo sequences through your own mailboxes). Postmark
enforces the same separation natively via Message Streams: bulk mail rides a
'broadcast' stream, never the transactional one, so a newsletter's reputation
can't touch anything else.

Env:
    POSTMARK_SERVER_TOKEN   server API token (Postmark → your server → API Tokens)
    MARKETING_FROM          verified sender, e.g. "Sid at Knowella <news@knowella.com>"
                            — the address (or its domain) must be a confirmed Sender
                            Signature / verified domain in Postmark, or every send 422s.

Batching: /email/batch takes up to 500 messages per call. Each message is fully
rendered by US (merge fields via personalize.fill_placeholders) — Postmark is a
dumb, excellent pipe, same philosophy as the rest of the app.
"""
from __future__ import annotations

import os

import httpx

BASE = "https://api.postmarkapp.com"
BATCH = 500


def _token() -> str:
    """The Postmark server token, under either name it has been stored as.

    The deployed .env sets POSTMARK_API while this module was written for
    POSTMARK_SERVER_TOKEN, which meant has_key() answered False and the whole
    marketing engine reported itself disconnected with a perfectly valid key
    sitting in the file. Accepting both removes the failure mode rather than
    trusting everyone to spell it the same way.
    """
    return (os.environ.get("POSTMARK_SERVER_TOKEN")
            or os.environ.get("POSTMARK_API")
            or os.environ.get("POSTMARK_TOKEN") or "")


def has_key() -> bool:
    return bool(_token())


def from_address() -> str:
    return os.environ.get("MARKETING_FROM", "")


def reply_to() -> str:
    """Where replies land. Without this every reply goes to the From address, which
    means sending as news@ requires news@ to be a real, watched mailbox. Setting it
    lets the newsletter come from a brand address while a human gets the answers —
    and replies to a newsletter are warm inbound, the last thing to drop on the floor.
    """
    return os.environ.get("MARKETING_REPLY_TO", "")


def _hdr() -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Postmark-Server-Token": _token(),
    }


def send_batch(messages: list[dict], stream: str | None = None) -> list[dict]:
    """Send up to 500 fully-rendered messages: [{to, subject, text_body, html_body?}].

    Returns Postmark's per-message results [{ErrorCode, Message, To, MessageID}, …] in
    order — ErrorCode 0 = accepted. Raises only on transport/auth-level failure, so a
    single bad address never kills the batch.
    """
    if not has_key():
        raise RuntimeError("POSTMARK_SERVER_TOKEN is not set — add it to .env and restart")
    sender = from_address()
    if not sender:
        raise RuntimeError("MARKETING_FROM is not set — e.g. 'Sid at Knowella <news@knowella.com>' "
                           "(must be a verified sender/domain in Postmark)")
    stream = stream or os.environ.get("POSTMARK_STREAM", "broadcast")
    out: list[dict] = []
    for i in range(0, len(messages), BATCH):
        chunk = messages[i:i + BATCH]
        payload = []
        for m in chunk:
            entry = {
                "From": sender,
                "To": m["to"],
                "Subject": m["subject"],
                "TextBody": m.get("text_body") or "",
                "MessageStream": stream,
                "TrackOpens": True,
            }
            rt = m.get("reply_to") or reply_to()
            if rt:
                entry["ReplyTo"] = rt
            if m.get("html_body"):
                entry["HtmlBody"] = m["html_body"]
                entry["TrackLinks"] = "HtmlOnly"
            out_headers = m.get("headers") or {}
            if out_headers:
                entry["Headers"] = [{"Name": k, "Value": v} for k, v in out_headers.items()]
            if m.get("metadata"):
                entry["Metadata"] = m["metadata"]   # echoed back in every webhook event
            payload.append(entry)
        r = httpx.post(f"{BASE}/email/batch", json=payload, headers=_hdr(), timeout=60.0)
        if r.status_code >= 400:
            raise RuntimeError(f"Postmark batch failed [{r.status_code}]: {r.text[:300]}")
        out.extend(r.json())
    return out
