"""One-click unsubscribe links for outreach emails.

A per-recipient token (the email + a short HMAC signature, base64url) goes in the
email footer as a clickable link. Clicking it hits /api/unsubscribe, which verifies
the signature and adds the address to the global do-not-contact list — lower friction
than "reply no thanks", and the one-click unsubscribe mailbox providers now expect.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os


def _secret() -> bytes:
    return (os.environ.get("UNSUB_SECRET")
            or os.environ.get("CLERK_SECRET_KEY")
            or "knowella-outreach-unsub").encode()


def _base_url() -> str:
    return (os.environ.get("APP_BASE_URL") or "https://outreach.knowella.com").rstrip("/")


def _sig(email: str) -> str:
    return hmac.new(_secret(), email.encode(), hashlib.sha256).hexdigest()[:16]


def token(email: str) -> str:
    e = (email or "").strip().lower()
    return base64.urlsafe_b64encode(f"{e}|{_sig(e)}".encode()).decode().rstrip("=")


def email_from_token(tok: str) -> str | None:
    """The email a token encodes, or None if the token is malformed/tampered."""
    try:
        raw = base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4)).decode()
        e, sig = raw.rsplit("|", 1)
        return e if hmac.compare_digest(sig, _sig(e)) else None
    except Exception:
        return None


def link(email: str) -> str:
    return f"{_base_url()}/api/unsubscribe?t={token(email)}"
