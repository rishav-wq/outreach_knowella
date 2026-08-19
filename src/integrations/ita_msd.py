"""OSHA injury records → leads.

`osha.py` listens for the handful of employers OSHA *cites* each month. This one
uses the much larger file underneath it: every large high-hazard establishment
must file its Form 300/301 case detail with OSHA, and OSHA publishes the lot.

For CY2024 that is 688,649 individual injuries at named establishments — street
address, EIN, the injured worker's job title, days away and restricted, and an
unscrubbed narrative of what they were doing. 216,487 of those (31.4%) are
musculoskeletal: overexertion, repetitive motion, bodily reaction. They land on
17,202 named employers.

That is the ergonomics buying signal, filed by the buyer themselves. A plant with
fourteen overexertion cases among its machine operators has a problem it has
already measured, already reported to the federal government, and is already
paying for in lost days.

Two things to keep straight, because getting either wrong makes the outreach
dishonest:

  * These are **self-reported injury records, not citations**. Nobody here has
    been cited, fined, or found at fault. `kind` is `injury_record` for exactly
    that reason — an email implying enforcement would be a factual error.
  * We open with the **aggregate**, never the individual case. "Your filings show
    14 overexertion cases among machine operators" is a business problem. "Your
    meat cutter strained their back lifting boxes in the cooler" is somebody's
    bad day, and reads as intrusive even though it is public.

The file is annual and ~500 MB, so this is an import an operator runs when a new
year publishes — not something to put on the poller.
"""
from __future__ import annotations

import csv
import re

from .. import signals

SOURCE_URL = "https://www.osha.gov/Establishment-Specific-Injury-and-Illness-Data"

# OIICS event division 7 — "overexertion and bodily reaction". This is the MSD
# definition: 71 overexertion involving outside sources, 72 repetitive motions
# involving microtasks, 73 other exertions, 74 bodily conditions. OSHA's codes are
# ML-predicted (`_pred` columns) and ~18% of rows carry none, so this undercounts
# rather than overcounts — which is the right direction for a claim we intend to
# put in an email.
MSD_DIVISION = "7"

# The band worth contacting. Below ~10 cases the signal is noise; above ~300 you
# are talking to Amazon, UPS and Walmart, who staff ergonomics teams in-house and
# were never going to buy this. The middle is ~2,300 employers, median 699 staff:
# large enough to employ a safety manager, small enough to need help.
MIN_CASES, MAX_CASES = 10, 300

csv.field_size_limit(10_000_000)


# --- establishment names are dirty, and that is worth ~12 points of match rate ---
#
# The name field is whatever the filer typed. Left alone, Apollo matches 68% of
# them; cleaned, 79%. Every rule below comes from an observed miss.

# A name that is only a site code ("005-PL001", "413-DC001") carries no company
# identity at all — skip it rather than guess.
_PURE_CODE = re.compile(r"^[\d\-\s]*(?:[A-Z]{1,3}\d{2,}|\d{2,}[A-Z\-]*\d*)[\d\-\s]*$", re.I)
# Site words appended to a company name. Deliberately excludes HOSPITAL, MEDICAL
# CENTER and HEALTH: in three of our top five industries those *are* the company,
# and stripping them turned "Emanuel Medical Center" into "Emanuel" and lost the
# match. The all-caps-tail rule below still catches them when they genuinely trail
# a company name ("HealthPartners Inc. LAKEVIEW HOSPITAL").
_FACILITY_TAIL = re.compile(
    r"\s+(?:DC\d*|FC\d*|PLANT\s*\d*|WAREHOUSE|DISTRIBUTION\s+CENTER|"
    r"FULFILLMENT\s+CENTER|STORE\s*#?\d*|BRANCH\s*#?\d*|FACILITY|TERMINAL)\b.*$", re.I)
_ROUTE_CODE = re.compile(r"\s+[A-Z]{2}-[A-Z]{3}-.*$")          # "... AA-JFK-NEW YORK"
_TRAILING_CODE = re.compile(r"\s*[-–]\s*[A-Z0-9]{1,6}\d[A-Z0-9]*\s*$", re.I)  # "LAX - B213"
_LEADING_CODE = re.compile(r"^\s*\d{2,}[\s\-]+")               # "027 EMANUEL MEDICAL CENTER"
_PARENS = re.compile(r"\s*\([^)]*\)\s*$")                      # "MARATHON CHEESE (MEDFORD)"
# A run of ALL-CAPS tokens after a name that has lower-case in it is a site label.
_CAPS_TAIL = re.compile(r"^(.*?[a-z].*?)\s+([A-Z][A-Z\-.]{2,}(?:\s+[A-Z][A-Z\-.]{2,})*)$")
_MULTISPACE = re.compile(r"\s{2,}")


def clean_company(name: str) -> tuple[str, str]:
    """Filer's establishment name → something Apollo can match.

    Returns (name, reason_unusable). An empty name means don't bother asking.
    """
    n = _MULTISPACE.sub(" ", (name or "").replace("\t", " ").strip())
    if not n:
        return "", "empty"
    if _PURE_CODE.match(n):
        return "", "site-code-only"
    n = _PARENS.sub("", n)
    n = _ROUTE_CODE.sub("", n)
    n = _TRAILING_CODE.sub("", n)
    n = _LEADING_CODE.sub("", n)
    n = _FACILITY_TAIL.sub("", n)
    m = _CAPS_TAIL.match(n)
    if m and len(m.group(1)) >= 4:
        n = m.group(1)
    n = n.strip(" ,.-")
    return (n, "") if len(n) >= 3 else ("", "too-short-after-clean")


def _txt(s: str) -> str:
    """The file pads fields with tabs and long runs of spaces."""
    return " ".join((s or "").split())


def _int(s: str) -> int:
    try:
        return int(_txt(s) or 0)
    except ValueError:
        return 0


# --- aggregation --------------------------------------------------------------


def aggregate(csv_path: str, min_cases: int = MIN_CASES,
              max_cases: int = MAX_CASES, naics_prefixes: tuple[str, ...] = (),
              rank: str = "cases") -> list[dict]:
    """The case file → one row per employer, ranked by MSD burden.

    Streams: the CY2024 file is ~500 MB and must not be read into memory.
    Keyed on EIN where present so "Walmart Inc" and "Wal-Mart Stores East, LP"
    don't fragment into separate employers.

    `naics_prefixes` narrows to one trade. The MSD story is physically different
    per industry — totes off a bottom rack in a DC, repositioning a patient in a
    hospital, baggage in a cargo hold — and copy written for all three is written
    for none of them.

    `rank="severity"` sorts by lost days per employee rather than raw case count.
    Raw counts just surface the biggest payrolls; 40 cases across 400 staff is a
    worse problem than 60 across 5,000, and far more likely to be felt.
    """
    emps: dict[str, dict] = {}
    for row in _rows(csv_path):
        if _txt(row.get("event_code_pred"))[:1] != MSD_DIVISION:
            continue
        if naics_prefixes and not _txt(row.get("naics_code")).startswith(naics_prefixes):
            continue
        raw = _txt(row.get("company_name")) or _txt(row.get("establishment_name"))
        if not raw:
            continue
        ein = _txt(row.get("ein"))
        key = ein or raw.lower()
        e = emps.get(key)
        if e is None:
            e = emps[key] = {
                "company_raw": raw, "ein": ein, "cases": 0, "days": 0,
                "naics": _txt(row.get("naics_code")),
                "industry": _txt(row.get("industry_description")),
                "city": _txt(row.get("city")), "state": _txt(row.get("state")),
                "employees": 0, "occupations": {},
            }
        e["cases"] += 1
        e["days"] += _int(row.get("dafw_num_away")) + _int(row.get("djtr_num_tr"))
        e["employees"] = max(e["employees"], _int(row.get("annual_average_employees")))
        occ = _txt(row.get("soc_description"))
        if occ and occ.lower() != "uncoded":
            e["occupations"][occ] = e["occupations"].get(occ, 0) + 1

    out = []
    for e in emps.values():
        if not (min_cases <= e["cases"] <= max_cases):
            continue
        name, why = clean_company(e["company_raw"])
        if not name:
            continue                       # a site code names nobody to contact
        e["company"] = name
        e["top_occupation"] = (max(e["occupations"].items(), key=lambda kv: kv[1])[0]
                               if e["occupations"] else "")
        # Days lost per head. Guarded: a missing headcount must not divide by zero,
        # and must not float an unknown-size employer to the top of the list.
        e["days_per_employee"] = round(e["days"] / e["employees"], 2) if e["employees"] else 0.0
        out.append(e)
    if rank == "severity":
        out.sort(key=lambda x: (-x["days_per_employee"], -x["cases"]))
    else:
        out.sort(key=lambda x: (-x["cases"], -x["days"]))
    return out


# NAICS 493 is warehousing and storage — the largest MSD block in the file and the
# easiest operation to write specific copy for.
WAREHOUSING = ("493",)


def _rows(csv_path: str):
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as fh:
        yield from csv.DictReader(fh)


# --- signal shape -------------------------------------------------------------


def claim(emp: dict, year: str = "") -> str:
    """The one sentence the opener is allowed to assert, and the reason this
    source exists. Aggregate only — never the individual injury narrative."""
    yr = f" in {year}" if year else ""
    occ = f" among {emp['top_occupation'].lower()}" if emp.get("top_occupation") else ""
    days = f", {emp['days']:,} days away or restricted" if emp.get("days") else ""
    return (f"{emp['company']} reported {emp['cases']} musculoskeletal injury cases"
            f"{occ}{yr} to OSHA{days}.")


def to_signal(emp: dict, year: str = "") -> dict:
    """An employer's injury record, shaped as a signal so it shares the queue,
    the dedupe and the source attribution with everything else."""
    return {
        "channel": "import", "platform": "osha_ita", "kind": "injury_record",
        "person": "", "company": emp["company"],
        "location": ", ".join(x for x in (emp.get("city"), emp.get("state")) if x),
        "state": emp.get("state", ""),
        "cases": emp["cases"], "days": emp["days"],
        "naics": emp.get("naics", ""), "industry": emp.get("industry", ""),
        "employees": emp.get("employees", 0),
        "occupation": emp.get("top_occupation", ""),
        "title": f"{emp['company']} — {emp['cases']} MSD cases",
        "text": claim(emp, year), "url": SOURCE_URL,
        # Route on what the employer IS, not on how we describe their problem.
        # The claim sentence says "musculoskeletal", which matched a campaign whose
        # ICP is ergonomics *practitioners* — 107 of the first 150 employers were
        # queued against a request-for-feedback pitch aimed at ergonomists rather
        # than a sales pitch aimed at the employer. The industry and the injured
        # occupation are the facts that decide which offer fits.
        "route_text": " ".join(x for x in (emp["company"], emp.get("industry", ""),
                                           emp.get("top_occupation", "")) if x),
        # No per-employer URL exists, so identity is the employer within the
        # filing year: re-importing the same year is a no-op, next year is new.
        "dedupe": signals.dedupe_key(
            "osha_ita", "", f"{emp.get('ein') or emp['company']}|{year}"),
    }


def import_employers(store, csv_path: str, year: str = "",
                     min_cases: int = MIN_CASES, max_cases: int = MAX_CASES,
                     limit: int = 0, naics_prefixes: tuple[str, ...] = (),
                     rank: str = "cases") -> dict:
    """Bulk file → signals queue. Returns counts; safe to re-run."""
    src = store.upsert_source("OSHA injury records (ITA)", "regulator", SOURCE_URL)
    emps = aggregate(csv_path, min_cases, max_cases, naics_prefixes, rank)
    if limit:
        emps = emps[:limit]
    new = 0
    for emp in emps:
        sig = to_signal(emp, year)
        sig["source_id"] = src
        if store.add_signal(sig):
            new += 1
    return {"employers": len(emps), "new": new, "source_id": src}
