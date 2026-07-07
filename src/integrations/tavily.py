"""Tavily search via REST (httpx). Aggregates web + news across many sites in one
call — the multi-source core. Skips gracefully (returns []) when no key is set, so
research degrades to homepage-only rather than crashing.
"""
from __future__ import annotations

import os

import httpx

ENDPOINT = "https://api.tavily.com/search"


def has_key() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY"))


def search(query: str, max_results: int = 4, topic: str = "general", days: int | None = None) -> list[dict]:
    """Return [{url, content, title, published}]; [] if no key or on error."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return []
    payload = {
        "api_key": key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
        "topic": topic,
    }
    if days:
        payload["days"] = days
    try:
        r = httpx.post(ENDPOINT, json=payload, timeout=20.0)
        r.raise_for_status()
        results = r.json().get("results", [])
        return [
            {
                "url": it.get("url", ""),
                "content": it.get("content", ""),
                "title": it.get("title", ""),
                "published": it.get("published_date"),
            }
            for it in results
        ]
    except Exception:
        return []
