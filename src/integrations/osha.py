"""OSHA enforcement → leads.

The rest of the Signals page listens for people talking. This one is different: the
US Department of Labor publishes, on a feed built for the purpose, a list of companies
it has just cited — with the violation, the penalty and the date. That is a named
business with a compliance problem that is public, expensive, dated, and legally
obliged to be fixed.

It is the opposite of a bought list. Apollo's 4,422 cold leads produced 9 replies and
0 meetings because nothing had happened to those people. Something just happened to
these ones, and we can say what it was in the first line of the email.

The feed itself carries no company name — titles are generic ("Houston utility
contractor"), the description is a bare date. The name only exists in the release
body, so each release is fetched and parsed. Volume is low by design: these are the
newsworthy cases, roughly a handful a month.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from .. import signals

FEED_URL = "https://www.osha.gov/news/newsreleases.xml"
UA = {"User-Agent": "Mozilla/5.0 (compatible; KnowellaOutreach/1.0; +https://outreach.knowella.com)"}

# Company names are matched by their legal suffix. It's the one reliably capitalised,
# unambiguous token in the prose — "OSHA cited Blazey Construction Services LLC after…"
_SUFFIX = r"(?:LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Company|Co\.|Ltd\.?|LP|LLP|PLLC)"
_NAME = re.compile(r"\b((?:[A-Z][\w&.'\-]*\s+){1,5}" + _SUFFIX + r")")
_CITY = re.compile(r"\b(?:in|at|near)\s+([A-Z][a-zA-Z.\-]+(?:\s[A-Z][a-zA-Z.\-]+)?,\s[A-Z][a-z]+)\b")
# Every release opens with a press dateline — "CORPUS CHRISTI, TX ‒ The U.S.
# Department of Labor has cited…" — which carries BOTH the location and the one
# plain-English sentence describing what the employer did. Note the separator is a
# figure dash (U+2012), not a hyphen; matching only the common dashes missed every
# release and fell through to scraping the page footer.
_DASH = "[\\-‐‑‒–—―−]"
_DATELINE = re.compile(r"^([A-Z][A-Z .,'&\-]{2,42}?)\s*" + _DASH + r"\s*(.{40,})$")
_BOILER = re.compile(r"\.gov means|site is secure|Information in some news releases|"
                     r"Scroll to Top|Release Number:|@dol\.gov", re.I)
_MONEY = re.compile(r"\$([\d,]+(?:\.\d+)?)\s*([KkMm]?)\b")
# Releases that aren't enforcement actions at all — policy announcements, alliances,
# appointments. They name no employer and must not become leads.
_NOT_ENFORCEMENT = re.compile(
    r"memorandum of understanding|alliance with|announces? (?:the )?appointment|"
    r"national safety stand-down|awards? \$|grant", re.I)
# Government and press bodies that appear in every release and are never the employer.
_NOT_A_COMPANY = re.compile(
    r"^(?:U\.?S\.?\s+)?(?:Department|Occupational|Office|Bureau|Administration|Agency|"
    r"Commission|Coast Guard|OSHA|Labor)\b", re.I)


_STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI",
    "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
}
# OSHA datelines are usually the regional or area office city, and about a third of
# them omit the state ("HOUSTON ‒ …"). Without a state the citation can't be placed
# on the map, so the unambiguous big cities are resolved by name.
_CITY_STATE = {
    "BOSTON": "MA", "NEW YORK": "NY", "PHILADELPHIA": "PA", "ATLANTA": "GA", "CHICAGO": "IL",
    "DALLAS": "TX", "KANSAS CITY": "MO", "DENVER": "CO", "SAN FRANCISCO": "CA", "SEATTLE": "WA",
    "HOUSTON": "TX", "AUSTIN": "TX", "SAN ANTONIO": "TX", "EL PASO": "TX", "FORT WORTH": "TX",
    "CORPUS CHRISTI": "TX", "LUBBOCK": "TX", "PHOENIX": "AZ", "TUCSON": "AZ", "LAS VEGAS": "NV",
    "LOS ANGELES": "CA", "SAN DIEGO": "CA", "SACRAMENTO": "CA", "FRESNO": "CA", "OAKLAND": "CA",
    "PORTLAND": "OR", "SALT LAKE CITY": "UT", "BOISE": "ID", "BILLINGS": "MT", "OMAHA": "NE",
    "WICHITA": "KS", "ST. LOUIS": "MO", "MINNEAPOLIS": "MN", "MILWAUKEE": "WI", "MADISON": "WI",
    "DETROIT": "MI", "CLEVELAND": "OH", "COLUMBUS": "OH", "CINCINNATI": "OH", "TOLEDO": "OH",
    "INDIANAPOLIS": "IN", "LOUISVILLE": "KY", "NASHVILLE": "TN", "MEMPHIS": "TN",
    "BIRMINGHAM": "AL", "MOBILE": "AL", "JACKSON": "MS", "NEW ORLEANS": "LA",
    "BATON ROUGE": "LA", "LITTLE ROCK": "AR", "OKLAHOMA CITY": "OK", "TULSA": "OK",
    "TAMPA": "FL", "ORLANDO": "FL", "MIAMI": "FL", "JACKSONVILLE": "FL", "FORT LAUDERDALE": "FL",
    "CHARLOTTE": "NC", "RALEIGH": "NC", "COLUMBIA": "SC", "CHARLESTON": "WV", "RICHMOND": "VA",
    "NORFOLK": "VA", "BALTIMORE": "MD", "PITTSBURGH": "PA", "HARRISBURG": "PA", "NEWARK": "NJ",
    "BUFFALO": "NY", "SYRACUSE": "NY", "ALBANY": "NY", "HARTFORD": "CT", "PROVIDENCE": "RI",
    "MANCHESTER": "NH", "PORTLAND, ME": "ME", "AUGUSTA": "ME", "BANGOR": "ME",
    "ANCHORAGE": "AK", "HONOLULU": "HI", "DES MOINES": "IA", "FARGO": "ND", "SIOUX FALLS": "SD",
    "CHEYENNE": "WY", "ALBUQUERQUE": "NM", "WASHINGTON": "DC",
}


def state_of(location: str, text: str = "") -> str:
    """Two-letter state for the map. The dateline's own suffix first, then the city,
    then a state named in the prose ('a Florida roofing company')."""
    loc = (location or "").strip()
    m = re.search(r",\s*([A-Za-z .]+)$", loc)
    if m:
        tail = m.group(1).strip().upper()
        if len(tail) == 2 and tail in _STATES.values():
            return tail
        if tail in _STATES:
            return _STATES[tail]
    city = re.sub(r",.*$", "", loc).strip().upper()
    if city in _CITY_STATE:
        return _CITY_STATE[city]
    for full, code in _STATES.items():
        if re.search(r"\b" + full + r"\b", text, re.I):
            return code
    return ""


def _penalty(text: str) -> int:
    """Dollars as an integer. '$343K' and '$264,380' both appear; the largest figure in
    a release is the proposed penalty (smaller ones are per-violation maximums)."""
    best = 0
    for m in _MONEY.finditer(text):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(2) or "").upper()
        v = v * 1_000 if unit == "K" else v * 1_000_000 if unit == "M" else v
        best = max(best, int(v))
    return best


def parse_release(title: str, url: str, html: str) -> dict | None:
    """One release page → a citation record, or None when it isn't an enforcement
    action. Returning None matters: a Coast Guard memorandum has no employer to sell
    to, and inventing one would poison the campaign with a government body."""
    if _NOT_ENFORCEMENT.search(title):
        return None
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" "))
    company = ""
    for cand in _NAME.findall(text):
        cand = cand.strip()
        if not _NOT_A_COMPANY.match(cand):
            company = cand
            break
    if not company:
        return None

    # Read the dateline paragraph rather than pattern-hunting the whole document:
    # the page repeats the release in several places and the footer is full of
    # near-miss text, so anchoring on the article's own opening is the honest read.
    location, lede = "", ""
    for p in soup.find_all("p"):
        s = p.get_text(" ", strip=True)
        if len(s) < 60 or _BOILER.search(s):
            continue
        m = _DATELINE.match(s)
        if m:
            location = " ".join(w if len(w) <= 2 else w.title() for w in m.group(1).split())
            lede = m.group(2).strip()
            break
        if not lede:
            lede = s                       # no dateline: first real paragraph will do
    if not location:
        c = _CITY.search(text)
        location = c.group(1) if c else ""
    lede = re.sub(r"\s+", " ", lede)[:400].strip()

    return {
        "company": company,
        "location": location,
        "state": state_of(location, text),
        "penalty": _penalty(title) or _penalty(text),
        "violation": lede or title,
        "title": title,
        "url": url,
    }


def fetch_citations(limit: int = 25) -> list[dict]:
    """The feed, then each release page. Low volume (a handful of items), so fetching
    every page is a few requests, not a crawl."""
    out = []
    for item in signals.fetch_feed(FEED_URL)[:limit]:
        try:
            r = httpx.get(item["url"], timeout=30.0, follow_redirects=True, headers=UA)
            r.raise_for_status()
        except Exception:
            continue                      # one unreachable release must not stop the rest
        rec = parse_release(item["title"], item["url"], r.text)
        if rec:
            out.append(rec)
    return out


def to_signal(rec: dict) -> dict:
    """A citation, shaped as a signal so it shares the queue, the dedupe and the
    source attribution with everything else."""
    pen = f" — ${rec['penalty']:,}" if rec.get("penalty") else ""
    return {
        "channel": "rss", "platform": "osha", "kind": "citation",
        "person": "", "company": rec["company"], "location": rec.get("location", ""),
        "state": rec.get("state", ""), "penalty": rec.get("penalty", 0),
        "title": f"{rec['company']}{pen}",
        "text": rec.get("violation", ""), "url": rec["url"],
        "dedupe": signals.dedupe_key("osha", rec["url"], rec["company"]),
    }


def poll(store) -> int:
    """New citations into the queue. Returns how many were new."""
    src = store.upsert_source("OSHA citations", "regulator", FEED_URL)
    n = 0
    for rec in fetch_citations():
        sig = to_signal(rec)
        sig["source_id"] = src
        if store.add_signal(sig):
            n += 1
    return n
