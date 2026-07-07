"""Lead enrichment — fill missing data from free/cheap sources.

- find_domain(company): company name -> website domain (Clearbit autocomplete, free,
  no key). STRICT name-match guard so we never return a *different* company's domain
  (e.g. "Cintas" must not become "cintasdecorrer.com"). Returns "" when unsure.
- find_email(domain, first, last): -> email (Hunter, free tier, needs HUNTER_API_KEY).

Both are graceful: "" on miss / no key / error — they never raise.
"""
from __future__ import annotations

import os
import re

import httpx

CLEARBIT = "https://autocomplete.clearbit.com/v1/companies/suggest"
HUNTER = "https://api.hunter.io/v2/email-finder"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def find_domain(company: str) -> str:
    """Best-effort company -> domain. Accepts a suggestion only if its name equals
    the query, or the query is the suggestion plus a suffix (e.g. 'Nucor Corp' ⊇
    'Nucor'); rejects more-specific different names. Returns '' if uncertain."""
    if not company:
        return ""
    nq = _norm(company)
    try:
        r = httpx.get(CLEARBIT, params={"query": company}, timeout=12)
        r.raise_for_status()
        for item in r.json():
            ns = _norm(item.get("name", ""))
            dom = (item.get("domain") or "").strip()
            if dom and ns and (ns == nq or nq.startswith(ns + " ")):
                return dom
    except Exception:
        pass
    return ""


def has_hunter() -> bool:
    return bool(os.environ.get("HUNTER_API_KEY"))


def find_email(domain: str, first: str, last: str) -> str:
    """Domain + name -> email (Hunter). '' on no key / no result / error."""
    key = os.environ.get("HUNTER_API_KEY")
    if not key or not domain or not (first or last):
        return ""
    try:
        r = httpx.get(HUNTER, params={
            "domain": domain, "first_name": first, "last_name": last, "api_key": key,
        }, timeout=20)
        if r.status_code != 200:
            return ""
        return ((r.json() or {}).get("data") or {}).get("email") or ""
    except Exception:
        return ""
