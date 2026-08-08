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
import re

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
      employee_ranges: ['lo,hi', ...]        (else derived from icp.company_size)
      seniorities: [owner|founder|c_suite|partner|vp|head|director|manager|senior|entry|intern]
      exclude_titles: [str]                  (person_not_titles — live-verified, undocumented)
      person_locations: [str]                (where the PERSON lives; `locations` = employer HQ)
      email_status: [verified|unverified|likely to engage|unavailable]
      hiring_job_titles: [str]               (companies with active postings for these roles)
      hiring_min_jobs: int                   (companies with at least N open roles)
      revenue_min / revenue_max: int         (annual revenue USD)
      naics_codes: [str]                     (organization_naics_codes — live-verified 2026-07-13,
                                              undocumented on people search but honored; any prefix
                                              length works, e.g. '484' matches all of 4841x/4842x)
      sic_codes: [str]                       (organization_sic_codes — same probe, honored)
      lookalike_seeds: [{id, label}]         (lookalike_person_ids — live-verified 2026-07-13:
                                              finds people similar to the seed leads; ANDs with
                                              the other filters; label is display-only)
      schools: [{id, label}]                 (person_education_school_ids — live-verified
                                              2026-07-13: alumni of these schools; multiple
                                              ids OR together. Ids come from search_schools;
                                              label is display-only)
    All live-probed against api_search (docs/outreach-campaign-fields-research.md);
    plan-gated filters may stop matching if the Apollo plan changes.
    """
    icp = cfg.get("icp") or {}
    ap = cfg.get("apollo") or {}
    f: dict = {}
    titles = ap.get("titles") or icp.get("titles") or []
    if titles:
        f["person_titles"] = titles
    if ap.get("exclude_titles"):
        f["person_not_titles"] = ap["exclude_titles"]
    if ap.get("seniorities"):
        f["person_seniorities"] = ap["seniorities"]
    locations = ap.get("locations") or icp.get("geographies") or []
    if locations:
        f["organization_locations"] = locations
    if ap.get("person_locations"):
        f["person_locations"] = ap["person_locations"]
    ranges = ap.get("employee_ranges") or _size_ranges(icp.get("company_size"))
    if ranges:
        f["organization_num_employees_ranges"] = ranges
    keywords = ap.get("keywords") or icp.get("industries") or []
    if keywords:
        f["q_organization_keyword_tags"] = keywords
    exclude = ap.get("exclude_keywords") or []
    if exclude:
        f["q_not_organization_keyword_tags"] = exclude
    if ap.get("email_status"):
        f["contact_email_status"] = ap["email_status"]
    if ap.get("hiring_job_titles"):
        f["q_organization_job_titles"] = ap["hiring_job_titles"]
        f["organization_num_jobs_range"] = {"min": int(ap.get("hiring_min_jobs") or 1)}
    elif ap.get("hiring_min_jobs"):
        f["organization_num_jobs_range"] = {"min": int(ap["hiring_min_jobs"])}
    seed_ids = [s.get("id") for s in (ap.get("lookalike_seeds") or []) if s.get("id")]
    if seed_ids:
        f["lookalike_person_ids"] = seed_ids
    school_ids = [s.get("id") for s in (ap.get("schools") or []) if s.get("id")]
    if school_ids:
        f["person_education_school_ids"] = school_ids
    if ap.get("naics_codes"):
        f["organization_naics_codes"] = [str(c) for c in ap["naics_codes"]]
    if ap.get("sic_codes"):
        f["organization_sic_codes"] = [str(c) for c in ap["sic_codes"]]
    if ap.get("revenue_min") or ap.get("revenue_max"):
        rr = {}
        if ap.get("revenue_min"):
            rr["min"] = int(ap["revenue_min"])
        if ap.get("revenue_max"):
            rr["max"] = int(ap["revenue_max"])
        f["revenue_range"] = rr
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
    # harvest Apollo's per-endpoint quota headers from every response we get anyway
    from . import apollo_send
    apollo_send.note_rate_headers(str(r.request.url.path), r.headers)
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


def normalize_linkedin_url(url: str) -> str:
    """Canonical form of a LinkedIn profile URL for dedup/matching:
    lowercase host+path, no protocol, no query, no trailing slash.
    'https://www.linkedin.com/in/Jane-Doe-123/?miniProfile=x' -> 'linkedin.com/in/jane-doe-123'."""
    u = (url or "").strip().lower()
    u = u.split("?", 1)[0].split("#", 1)[0]
    u = u.replace("https://", "").replace("http://", "")
    if u.startswith("www."):
        u = u[4:]
    return u.rstrip("/")


def parse_headline(headline: str) -> tuple[str, str]:
    """(title, company) from a LinkedIn headline. Headlines are freeform —
    'VP Ops at Acme Logistics | Dad | Speaker' — so take the first segment and
    split on the last ' at ' / ' @ '. Best-effort: bad parses only weaken the
    Apollo match (the profile URL is the primary key), never corrupt the lead."""
    seg = (headline or "").split("|")[0].split("·")[0].strip()
    for sep in (" at ", " @ "):
        if sep in seg:
            title, company = seg.rsplit(sep, 1)
            return title.strip(), company.strip()
    return seg, ""


def match_commenters(commenters: list[dict]) -> tuple[list[Lead], int]:
    """Enrich LinkedIn-captured people via bulk_match keyed on their PROFILE URL —
    the highest-fidelity match key Apollo accepts (name/company only assist it).
    LinkedIn is used purely as a pointer; all contact data comes from Apollo's
    own database (~1 credit per matched person, like any reveal).

    commenters: [{name, profile_url, headline}]. Returns (leads, credits) — one
    Lead per input, in order. Unmatched people become skeleton Leads built from
    the captured name/headline (no email; downstream enrichment may fill gaps)."""
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    hdr = {"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key}
    leads: list[Lead] = []
    credits = 0
    for i in range(0, len(commenters), MATCH_CHUNK):
        chunk = commenters[i:i + MATCH_CHUNK]
        details = []
        for c in chunk:
            title, company = parse_headline(c.get("headline") or "")
            d: dict = {"linkedin_url": c.get("profile_url") or ""}
            if c.get("name"):
                d["name"] = c["name"]
            if company:
                d["organization_name"] = company
            details.append(d)
        r = httpx.post(MATCH_ENDPOINT, json={"details": details, "reveal_personal_emails": False},
                       headers=hdr, timeout=60.0)
        _raise_for_status(r)
        j = r.json()
        credits += int(j.get("credits_consumed") or 0)
        matches = j.get("matches") or []
        for pos, c in enumerate(chunk):
            m = matches[pos] if pos < len(matches) else None
            if m:
                lead = _person_to_lead(m)
                if not lead.linkedin_url:
                    lead.linkedin_url = c.get("profile_url") or ""
            else:
                # Apollo doesn't know this person — keep what the capture saw
                title, company = parse_headline(c.get("headline") or "")
                name = (c.get("name") or "").strip()
                first, _, last = name.partition(" ")
                lead = Lead(first_name=first, last_name=last, title=title, company=company,
                            linkedin_url=c.get("profile_url") or "")
            leads.append(lead)
    return leads, credits


COMPANY_ENDPOINT = "https://api.apollo.io/api/v1/mixed_companies/search"


def search_schools(q: str, limit: int = 8) -> list[dict]:
    """Resolve a typed university name to Apollo school choices: [{id, name}].

    Apollo's education filter is id-based (schools are organization records), and
    its autocomplete API isn't reachable with our key — but the documented
    q_organization_name search works as a resolver. The top hit isn't always the
    school ('MIT' ranks MIT Technology Review first), so callers should show the
    choices and let the user pick, not auto-take the first. Searching is free.
    """
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    hdr = {"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key}
    r = httpx.post(COMPANY_ENDPOINT, json={"q_organization_name": q, "page": 1, "per_page": limit},
                   headers=hdr, timeout=30.0)
    _raise_for_status(r)
    j = r.json()
    orgs = j.get("organizations") or j.get("accounts") or []
    return [{"id": o.get("id"), "name": o.get("name") or ""} for o in orgs if o.get("id")]


def search_total(cfg: dict) -> int:
    """How many people match the campaign's filters right now — FREE, no credits.

    api_search returns the match count as a TOP-LEVEL `total_entries` (there is
    no `pagination` object on this endpoint, unlike mixed_companies/search).
    This is the same number Apollo's People tab shows for identical filters, so
    the UI can surface it for cross-checking before any paid reveal.
    """
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    hdr = {"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key}
    payload = {**_build_filters(cfg), "page": 1, "per_page": 1}
    r = httpx.post(ENDPOINT, json=payload, headers=hdr, timeout=30.0)
    _raise_for_status(r)
    return int(r.json().get("total_entries") or 0)


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


# --- resolving a company we already know by name ------------------------------
# Everything above starts from an ICP filter and asks Apollo "who matches?". This
# starts from the other end: a specific named employer (an OSHA citation, a form
# fill) where we need the org record and then its safety leadership.

# The buyer for an OSHA citation isn't a job title in the abstract — it's whoever
# has to answer for it. Ordered from most to least accountable; Apollo matches these
# as partials, so "safety" alone would drag in "safety driver" and worse.
SAFETY_TITLES = [
    "ehs director", "ehs manager", "director of safety", "safety director",
    "vp safety", "vice president safety", "health and safety manager",
    "environmental health and safety", "safety manager", "hse manager",
    "risk manager", "compliance manager", "plant manager", "operations director",
]


def find_org(name: str, limit: int = 5) -> list[dict]:
    """Company name → Apollo organisation candidates [{id, name, domain}]. Free.

    Returns several, deliberately. Legal names from a citation ("Blazey Construction
    Services LLC") don't always rank first against Apollo's index, and silently
    taking the top hit is how you email the wrong company about a fatality.
    """
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    hdr = {"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key}
    q = re.sub(r"\b(LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Co\.|Ltd\.?|LP|LLP|PLLC)\b\.?",
               "", name, flags=re.I).strip(" ,.")     # the suffix hurts the match
    r = httpx.post(COMPANY_ENDPOINT, json={"q_organization_name": q or name, "page": 1, "per_page": limit},
                   headers=hdr, timeout=30.0)
    _raise_for_status(r)
    j = r.json()
    out = []
    for o in (j.get("organizations") or j.get("accounts") or []):
        if not o.get("id"):
            continue
        out.append({"id": o["id"], "name": o.get("name") or "",
                    "domain": _domain(o), "employees": o.get("estimated_num_employees") or 0,
                    "industry": o.get("industry") or "",
                    "location": ", ".join(x for x in [o.get("city"), o.get("state")] if x)})
    return out


def contacts_at_org(org_id: str, titles: list[str] | None = None,
                    limit: int = 5, person_ids: list[str] | None = None) -> tuple[list[Lead], int]:
    """The safety leadership at one org → revealed leads, and the credits it cost.
    Falls back to any senior contact when nobody carries a safety title: a small
    contractor often has no EHS function, which is rather the point of the pitch."""
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    hdr = {"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key}
    base = {"organization_ids": [org_id]}
    previews = _search_previews({**base, "person_titles": titles or SAFETY_TITLES}, limit, hdr)
    if not previews:
        previews = _search_previews({**base, "person_seniorities": ["owner", "founder", "c_suite",
                                                                    "vp", "director"]}, limit, hdr)
    if person_ids:            # the human picked; reveal exactly those and nobody else
        chosen = [p for p in previews if p.get("id") in set(person_ids)]
        previews = chosen or previews[:1]
    if not previews:
        return [], 0
    return _reveal(previews, hdr)


# Which of three safety people at one company should hear about a citation?
# Emailing all of them is the failure mode: colleagues compare notes, near-identical
# cold mail reads as a blast, and the single shot a real trigger buys you is gone.
# So rank by whose job the citation actually IS, and default to sending one.
_FUNCTION = [
    (re.compile(r"\b(ehs|hse|e\.h\.s)\b", re.I), 5, "EHS is their function"),
    (re.compile(r"environment\w*[, ]+health[, ]+(and )?safety", re.I), 5, "EHS is their function"),
    (re.compile(r"\bhealth and safety\b", re.I), 5, "health and safety"),
    (re.compile(r"\bsafety\b", re.I), 4, "safety in the title"),
    (re.compile(r"\b(risk|loss prevention|compliance)\b", re.I), 3, "risk/compliance"),
    (re.compile(r"\b(plant|operations|facilit)\w*", re.I), 2, "runs the site"),
]
_SENIORITY = [
    (re.compile(r"\b(chief|vp|vice president|head of)\b", re.I), 3, "senior"),
    (re.compile(r"\bdirector\b", re.I), 2, "director"),
    (re.compile(r"\bmanager\b", re.I), 1, "manager"),
]
# A qualifier that narrows the remit: "Fleet Safety" owns vehicles, not the plant
# where the citation happened. Still a safety person, just not THE one.
_NARROWING = re.compile(r"\b(fleet|region\w*|district|service|driver|transport)\b", re.I)


def score_title(title: str) -> tuple[int, str]:
    """How likely is this person the one who has to answer for the citation?"""
    t = title or ""
    fn = max(((w, why) for rx, w, why in _FUNCTION if rx.search(t)), default=(0, ""))
    sn = max(((w, why) for rx, w, why in _SENIORITY if rx.search(t)), default=(0, ""))
    narrow = 1 if _NARROWING.search(t) else 0
    why = ", ".join(x for x in (fn[1], sn[1]) if x) or "no safety signal in the title"
    if narrow:
        why += " — but a narrowed remit"
    return fn[0] + sn[0] - narrow, why


def preview_contacts_at_org(org_id: str, limit: int = 5) -> list[dict]:
    """Who's in safety at this org — masked previews only. FREE: no reveal, no
    credits. Lets the UI show what it found before anyone commits to spending."""
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    hdr = {"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key}
    base = {"organization_ids": [org_id]}
    pv = _search_previews({**base, "person_titles": SAFETY_TITLES}, limit, hdr)
    if not pv:
        pv = _search_previews({**base, "person_seniorities": ["owner", "founder", "c_suite",
                                                              "vp", "director"]}, limit, hdr)
    out = []
    for p in pv:
        sc, why = score_title(p["title"])
        out.append({"id": p["id"], "first_name": p["first_name"], "title": p["title"],
                    "score": sc, "why": why})
    out.sort(key=lambda x: -x["score"])
    return out
