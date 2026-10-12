"""People and companies: one record per person, one per company (KnowCRM phase 1).

Until now a "lead" was a row per campaign (`leads`, _id = "campaign::email"), so one
person in three campaigns was three unrelated rows, and there was no company record at
all (docs/knowcrm-requirements-audit.md §4.2). From here:

- `people`: one row per person, the thing the UI calls a lead.
- `companies`: one row per company, matched by web domain.
- `leads` stays exactly as it is, now meaning "a person in a campaign" (an enrollment),
  and gains `person_id` / `company_id`. Research, drafts, sends and replies are keyed
  by the enrollment id, so none of them move.

This module is the pure part: how a lead's identity and company are worked out. The
store (store_mongo.py) does the reads and writes.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

# Personal and ISP mail domains. A company is never made from one of these (two people
# at gmail.com are not colleagues), and the customer guard never matches on them.
FREEMAIL = frozenset("""
gmail.com googlemail.com yahoo.com yahoo.co.in yahoo.co.uk ymail.com rocketmail.com
hotmail.com hotmail.co.uk outlook.com live.com msn.com aol.com icloud.com me.com mac.com
protonmail.com proton.me gmx.com gmx.net mail.com zoho.com yandex.com yandex.ru qq.com
163.com 126.com rediffmail.com comcast.net att.net sbcglobal.net verizon.net cox.net
charter.net bellsouth.net earthlink.net optonline.net frontier.com windstream.net
""".split())

SOURCE_TYPES = ("apollo", "csv", "manual", "linkedin", "knowella", "signal", "")
_APOLLO_ID = re.compile(r"^[0-9a-f]{24}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def norm_email(e: str | None) -> str:
    e = (e or "").strip().lower()
    return e if "@" in e and " " not in e else ""


def norm_domain(d: str | None) -> str:
    """'https://www.Acme.com/about' -> 'acme.com'. '' when it isn't a domain."""
    d = (d or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0].split("?")[0].split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    return d if "." in d and " " not in d else ""


def company_domain_of(email: str, domain: str, org: dict | None) -> str:
    """The company's web domain: the lead's own domain field, else Apollo's org domain,
    else the email's domain. Never a personal-mail domain."""
    for cand in (domain, (org or {}).get("primary_domain"), (org or {}).get("website_url"),
                 email.split("@", 1)[1] if "@" in email else ""):
        d = norm_domain(cand)
        if d and d not in FREEMAIL:
            return d
    return ""


def norm_linkedin(url: str | None) -> str:
    """'https://www.linkedin.com/in/Jane-Doe/?x=1' -> 'linkedin.com/in/jane-doe'."""
    u = (url or "").strip().lower()
    u = re.sub(r"^[a-z]+://", "", u).split("?")[0].split("#")[0].rstrip("/")
    if u.startswith("www."):
        u = u[4:]
    return u if u.startswith("linkedin.com/in/") else ""


def name_key(first: str, last: str, domain: str) -> str:
    """Last resort identity for a person with no email, Apollo id or LinkedIn: name at a
    company domain. Empty when either part is missing (never match on a name alone)."""
    n = re.sub(r"\s+", " ", f"{first} {last}".strip().lower())
    return f"{n}|{domain}" if n and domain else ""


def identity(lead: dict) -> dict:
    """The keys a person is matched on, strongest first: email, Apollo person id,
    LinkedIn URL, name at domain. `lead` is a stored lead (Lead.model_dump())."""
    raw = lead.get("raw") or {}
    org = raw.get("organization") or {}
    email = norm_email(lead.get("email") or raw.get("email"))
    domain = company_domain_of(email, lead.get("company_domain", ""), org)
    # Apollo ids are 24 hex characters. A CSV row's own "id" column (raw holds the row)
    # would otherwise look like one and merge unrelated people.
    aid = str(raw.get("id") or "").strip().lower()
    oid = str(org.get("id") or raw.get("organization_id") or "").strip().lower()
    return {
        "email": email,
        "apollo_id": aid if _APOLLO_ID.match(aid) else "",
        "linkedin": norm_linkedin(lead.get("linkedin_url") or raw.get("linkedin_url")),
        "name_key": name_key(lead.get("first_name", ""), lead.get("last_name", ""), domain),
        "domain": domain,
        "apollo_org_id": oid if _APOLLO_ID.match(oid) else "",
    }


def source_type(lead_source: str) -> str:
    s = (lead_source or "").lower()
    if s.startswith("linkedin"):
        return "linkedin"
    if s in ("apollo", "csv", "manual", "knowella", "signal"):
        return s
    return "csv" if s in ("import", "upload") else (s or "")


def person_fields(lead: dict) -> dict:
    """What a lead row tells us about the person. Refreshed on every new sighting
    (Apollo's data is newer); never touches owner, stage, notes or anything a person
    typed in the app."""
    raw = lead.get("raw") or {}
    ids = identity(lead)
    out = {
        "first_name": lead.get("first_name", "") or raw.get("first_name", ""),
        "last_name": lead.get("last_name", "") or raw.get("last_name", ""),
        "title": lead.get("title", "") or raw.get("title", ""),
        "headline": raw.get("headline") or "",
        "seniority": raw.get("seniority") or "",
        "departments": list(raw.get("departments") or []),
        "city": raw.get("city") or "", "state": raw.get("state") or "",
        "country": raw.get("country") or "", "time_zone": raw.get("time_zone") or "",
        "company": lead.get("company", "") or (raw.get("organization") or {}).get("name", ""),
        "company_domain": ids["domain"],
        "linkedin_url": ids["linkedin"],
        "apollo_id": ids["apollo_id"],
        "name_key": ids["name_key"],
    }
    return {k: v for k, v in out.items() if v not in ("", [], None)}


def company_fields(lead: dict) -> dict:
    """What a lead row tells us about its company, from Apollo's stored org record."""
    raw = lead.get("raw") or {}
    org = raw.get("organization") or {}
    ids = identity(lead)
    phone = (org.get("primary_phone") or {}).get("sanitized_number") if isinstance(org.get("primary_phone"), dict) else ""
    out = {
        "name": org.get("name") or lead.get("company", ""),
        "domain": ids["domain"],
        "apollo_org_id": ids["apollo_org_id"],
        "phone": phone or org.get("sanitized_phone") or org.get("phone") or "",
        "industry": org.get("industry") or "",
        "industries": list(org.get("industries") or []),
        "naics_codes": [str(x) for x in (org.get("naics_codes") or [])],
        "sic_codes": [str(x) for x in (org.get("sic_codes") or [])],
        "employees": org.get("estimated_num_employees") or None,
        "revenue": org.get("organization_revenue_printed") or "",
        "city": org.get("city") or "", "state": org.get("state") or "", "country": org.get("country") or "",
        "linkedin_url": org.get("linkedin_url") or "",
        "website_url": org.get("website_url") or "",
        "founded_year": org.get("founded_year") or None,
    }
    return {k: v for k, v in out.items() if v not in ("", [], None)}


# --- stages, interests (defaults; Sid confirms, decision #7 and #9) -----------------
# From the earlier plan (docs/bdr-playbook-crm-plan.md §4.2). The last entries of each
# list are closing stages, kept out of the pipeline strip.
LEAD_STAGES = ["New", "Contacted", "Replied", "Interested", "Meeting booked",
               "Not interested", "Wrong person", "Do not contact"]
LEAD_OPEN = LEAD_STAGES[:5]
COMPANY_STAGES = ["Target", "Working", "Engaged", "Meeting set", "Opportunity",
                  "Customer", "Not a fit", "Nurture"]
COMPANY_OPEN = COMPANY_STAGES[:5]
# Knowella's own onboarding list (customerweb onboarding), so a product user's answers
# and a lead's interests are the same vocabulary (audit §3.7).
INTERESTS = {
    "Operations": ["Onboarding and training", "Forms and data collection", "Employee check-ins",
                   "Task execution"],
    "Supply Chain & Logistics": ["RFP and quotes", "Freight and load workflows", "Supplier onboarding",
                                 "Dock scheduling", "Fleet operations"],
    "Workplace Safety": ["EHS programs", "Ergonomic analysis", "Incident and case management",
                         "Compliance tracking"],
    "Other": ["Other"],
}
ALL_INTERESTS = [i for group in INTERESTS.values() for i in group]
NOTE_MAX = 5000


def derived_lead_stage(facts: dict) -> str:
    """A lead's stage from what actually happened, for someone nobody has staged by hand.
    facts: {suppressed, meeting, labels (reply classes), replied, sent}."""
    labels = set(facts.get("labels") or [])
    if facts.get("suppressed") or "opt_out" in labels:
        return "Do not contact"
    if facts.get("meeting"):
        return "Meeting booked"
    if "interested" in labels:
        return "Interested"
    if "not_interested" in labels:
        return "Not interested"
    if facts.get("replied") or labels:
        return "Replied"
    if facts.get("sent"):
        return "Contacted"
    return "New"


def derived_company_stage(lead_stages: list[str]) -> str:
    s = set(lead_stages)
    if "Meeting booked" in s:
        return "Meeting set"
    if s & {"Interested", "Replied"}:
        return "Engaged"
    if s & {"Contacted", "Not interested", "Wrong person", "Do not contact"}:
        return "Working"
    return "Target"
