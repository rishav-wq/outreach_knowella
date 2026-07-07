"""Email verification — drop dead/risky addresses before research or send.

Default provider: MillionVerifier (cheap, good free tier). Graceful skip when no
key (returns 'unknown', never blocks), so the pipeline runs without it until you
set MILLIONVERIFIER_API_KEY. A bounce rate over ~3-4% wrecks sending reputation,
so this is cheap insurance for the expensive infra downstream.
"""
from __future__ import annotations

import os

import httpx

ENDPOINT = "https://api.millionverifier.com/api/v3/"

# MillionVerifier 'result' -> our verdict
_MAP = {
    "ok": "deliverable",
    "invalid": "undeliverable",
    "disposable": "undeliverable",
    "catch_all": "risky",
    "unknown": "risky",
}


def has_key() -> bool:
    return bool(os.environ.get("MILLIONVERIFIER_API_KEY"))


def verify(email: str) -> str:
    """Return deliverable | undeliverable | risky | unknown.

    'unknown' on missing key or any API error — we fail OPEN so a verifier outage
    never silently halts the pipeline (the caller decides whether to block).
    """
    key = os.environ.get("MILLIONVERIFIER_API_KEY")
    if not key or not email:
        return "unknown"
    try:
        r = httpx.get(ENDPOINT, params={"api": key, "email": email, "timeout": 10}, timeout=20.0)
        r.raise_for_status()
        result = (r.json().get("result") or "").lower()
        return _MAP.get(result, "unknown")
    except Exception:
        return "unknown"
