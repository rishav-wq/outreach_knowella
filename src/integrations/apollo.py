"""Lead source — Apollo people search.

Uses Apollo's API-caller search endpoint (mixed_people/api_search). Needs a paid
plan with API access + a key minted in the Apollo API portal (developer.apollo.io).
Two-step pull, matching how Apollo actually works:
  1. api_search finds matching people — FREE, but masked (first name, title,
     company name, and an Apollo id only; last name / domain / email hidden).
  2. bulk_match reveals each found person — full name, company domain, and work
     email — and COSTS ~1 Apollo credit per contact.
So a 250-contact pull costs ~250 credits. fetch_leads returns (leads, credits)
and the caller surfaces the spend. Records Apollo can't enrich are kept from the
masked preview (name + company only) and our own enrichment fills gaps downstream.

Filters mirror an Apollo people search and come from the campaign's `icp` plus an
optional `apollo` block (see _build_filters).
"""
from __future__ import annotations

import os

import httpx

from ..models import Lead

# The old mixed_people/search is deprecated for API callers (returns 422);
# api_search is the current people-search endpoint.
ENDPOINT = "https://api.apollo.io/v1/mixed_people/api_search"
MATCH_ENDPOINT = "https://api.apollo.io/api/v1/people/bulk_match"
PER_PAGE = 100      # Apollo max per page (search)
MATCH_CHUNK = 10    # Apollo max records per bulk_match call
MAX_PAGES = 60      # safety cap (60 * 100 = 6000 leads) so a runaway can't loop


def has_key() -> bool:
    return bool(os.environ.get("APOLLO_API_KEY"))


def _size_ranges(size) -> list[str]:
    """'50-500' -> ['50,500']; '200' -> ['200,200']. Apollo wants 'lo,hi' strings."""
    if not size:
        return []
    s = str(size).replace(" ", "")
    if "-" in s:
        lo, hi = s.split("-", 1)
        return [f"{lo},{hi}"]
    return [f"{s},{s}"]


def _domain(org: dict) -> str:
    d = org.get("primary_domain") or org.get("website_url") or ""
    return d.replace("https://", "").replace("http://", "").strip("/")


def _build_filters(cfg: dict) -> dict:
    """Apollo people-search filters from the campaign's icp + optional apollo block.

    apollo block (all optional) overrides/extends the icp:
      titles, locations, keywords, exclude_keywords: [str]
      employee_ranges: ['lo,hi', ...]   (else derived from icp.company_size)
    """
    icp = cfg.get("icp") or {}
    ap = cfg.get("apollo") or {}
    f: dict = {}
    titles = ap.get("titles") or icp.get("titles") or []
    if titles:
        f["person_titles"] = titles
    locations = ap.get("locations") or icp.get("geographies") or []
    if locations:
        f["organization_locations"] = locations
    ranges = ap.get("employee_ranges") or _size_ranges(icp.get("company_size"))
    if ranges:
        f["organization_num_employees_ranges"] = ranges
    keywords = ap.get("keywords") or icp.get("industries") or []
    if keywords:
        f["q_organization_keyword_tags"] = keywords
    exclude = ap.get("exclude_keywords") or []
    if exclude:
        f["q_not_organization_keyword_tags"] = exclude
    return f


def _person_to_lead(p: dict) -> Lead:
    org = p.get("organization") or {}
    email = p.get("email") or ""
    if "not_unlocked" in email:   # Apollo masks emails in search; enrich later
        email = ""
    return Lead(
        first_name=p.get("first_name") or "",
        last_name=p.get("last_name") or "",
        title=p.get("title") or "",
        company=org.get("name") or "",
        company_domain=_domain(org),
        email=email,
        linkedin_url=p.get("linkedin_url") or "",
        raw=p,
    )


def _raise_for_status(r: httpx.Response) -> None:
    if r.status_code == 403:
        raise RuntimeError(
            "Apollo returned 403: this key can't use the people-search API. "
            "Create a key in the Apollo API portal (developer.apollo.io) on a plan with "
            "API access, then set APOLLO_API_KEY in .env. Or export a CSV from Apollo and use Import CSV."
        )
    if r.status_code >= 400:
        try:
            reason = r.json().get("error") or r.text[:200]
        except Exception:
            reason = r.text[:200]
        raise RuntimeError(f"Apollo search failed [{r.status_code}]: {reason}")


def _search_previews(filters: dict, limit: int, hdr: dict, known_ids: set | None = None) -> list[dict]:
    """Paginate api_search collecting masked previews: {id, first_name, title, company}.

    Skips people whose Apollo id is in `known_ids` (already pulled into this
    campaign) and keeps paging for genuinely NEW ones — so a repeat pull never
    re-reveals (re-charges for) contacts you already have.
    """
    known_ids = known_ids or set()
    previews: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        if len(previews) >= limit:
            break
        payload = {**filters, "page": page, "per_page": PER_PAGE}
        r = httpx.post(ENDPOINT, json=payload, headers=hdr, timeout=30.0)
        _raise_for_status(r)
        people = r.json().get("people") or []
        if not people:
            break
        for p in people:
            pid = p.get("id")
            if pid and pid in known_ids:
                continue   # already in this campaign — don't spend a reveal credit on it
            org = p.get("organization") or {}
            previews.append({"id": pid, "first_name": p.get("first_name") or "",
                             "title": p.get("title") or "", "company": org.get("name") or ""})
            if len(previews) >= limit:
                break
        if len(people) < PER_PAGE:   # last page of the whole search
            break
    return previews[:limit]


def _reveal(previews: list[dict], hdr: dict) -> tuple[list[Lead], int]:
    """bulk_match the previews' ids → full leads (name, domain, email). Costs credits."""
    ids = [pv["id"] for pv in previews if pv.get("id")]
    leads: list[Lead] = []
    credits = 0
    revealed: set[str] = set()
    for i in range(0, len(ids), MATCH_CHUNK):
        chunk = ids[i:i + MATCH_CHUNK]
        r = httpx.post(MATCH_ENDPOINT, json={"details": [{"id": x} for x in chunk],
                                             "reveal_personal_emails": False}, headers=hdr, timeout=60.0)
        _raise_for_status(r)
        j = r.json()
        credits += int(j.get("credits_consumed") or 0)
        for m in (j.get("matches") or []):
            if not m:
                continue
            leads.append(_person_to_lead(m))
            if m.get("id"):
                revealed.add(m["id"])
    # keep anything Apollo couldn't enrich, from the masked preview (name + company only)
    for pv in previews:
        if pv.get("id") and pv["id"] not in revealed:
            leads.append(Lead(first_name=pv["first_name"], title=pv["title"], company=pv["company"]))
    return leads, credits


def fetch_leads(cfg: dict, limit: int = 250, reveal: bool = True,
                known_ids: set | None = None) -> tuple[list[Lead], int]:
    """Pull up to `limit` NEW people matching the campaign's Apollo filters.

    `known_ids` = Apollo person ids already in the campaign; they're skipped
    during search so we only reveal (and charge for) genuinely new contacts.
    Returns (leads, credits_consumed). With reveal=True (default) each new
    person is enriched via bulk_match — full name + domain + work email — at
    ~1 Apollo credit each. reveal=False returns masked previews for free.
    """
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    hdr = {"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key}
    previews = _search_previews(_build_filters(cfg), limit, hdr, known_ids)
    if not reveal:
        return [Lead(first_name=pv["first_name"], title=pv["title"], company=pv["company"]) for pv in previews], 0
    return _reveal(previews, hdr)
