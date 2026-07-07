"""Fetch a URL and return clean, readable text. No API key needed.

Used by the homepage/careers research source — the one source that costs nothing
and works for any company with a website.
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; outreach-agent research bot)"}
_STRIP = ["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]


def fetch_text(url: str, timeout: float = 12.0, max_chars: int = 8000) -> str | None:
    """Return cleaned page text, or None on any failure (caller treats as 'no doc')."""
    try:
        r = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(_STRIP):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        return text[:max_chars] if len(text) > 50 else None
    except Exception:
        return None
