"""Lead source — CSV (an Apollo UI export, or any list).

The universal lead adapter: works on any plan and with any provider's export,
so the engine never depends on a paid search API. Header matching is flexible
(case-insensitive, common aliases) to absorb Apollo/Hunter/manual column naming.
"""
from __future__ import annotations

import csv

from ..models import Lead


def _get(row: dict, *names: str) -> str:
    low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
    for n in names:
        if low.get(n.lower()):
            return low[n.lower()]
    return ""


def _domain(s: str) -> str:
    return s.replace("https://", "").replace("http://", "").strip("/").split("/")[0]


def from_csv(path: str) -> list[Lead]:
    leads: list[Lead] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            email = _get(row, "email", "email address")
            if "not_unlocked" in email:  # Apollo's locked-email placeholder
                email = ""
            domain = _domain(_get(row, "company domain", "primary domain", "website",
                                  "company website", "domain"))
            leads.append(Lead(
                first_name=_get(row, "first name", "first_name"),
                last_name=_get(row, "last name", "last_name"),
                title=_get(row, "title", "job title"),
                company=_get(row, "company", "company name", "company name for emails",
                             "organization name", "account name",
                             "estab_name", "establishment name", "organization"),  # incl. OSHA exports
                company_domain=domain,
                email=email,
                linkedin_url=_get(row, "person linkedin url", "linkedin url", "linkedin"),
                raw=dict(row),
            ))
    return leads
