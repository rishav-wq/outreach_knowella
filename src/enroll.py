"""Who may be added to a campaign (KnowCRM phase 1; docs/knowcrm-requirements-audit.md
§3.1 and §11.6). Checked for every new campaign row, whatever adds it: an Apollo pull,
a CSV, the LinkedIn capture, a citation, the Library. Defaults for Sid to confirm
(decision #5):

- one running campaign per person: someone waiting to be emailed (pulled in the last
  30 days), or whose sequence is still going, can't be added to another;
- 90 days' cooling-off after a sequence ends (the playbook's own recycle rule);
- a lead owned by one rep can't be put in another rep's campaign;
- at most 2 people from one company in one campaign (the October audit found 124
  at a single firm);
- never someone at an existing Knowella customer (the customer guard, 35a).

An admin can override all of these for one add from the Library (`force`). The
do-not-contact list is separate and absolute: nobody overrides it.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from . import crm

COOLDOWN_DAYS = 90
MAX_PER_COMPANY = 2
# Rows that will still be emailed: slated for contact, so the person is "in" the campaign.
PENDING = {"new", "researched", "drafted", "gated", "queued", "error"}
# ...unless the row has sat unsent this long: then it was abandoned, and blocking the
# person from every other campaign forever helps nobody. (On 12 Oct, 626 of 1,158
# never-emailed rows were over 30 days old.)
PENDING_STALE_DAYS = 30

MESSAGES = {
    "running": "already in a running campaign",
    "cooling": "contacted recently (90 days' cooling-off)",
    "owned": "another rep's lead",
    "company_cap": f"{MAX_PER_COMPANY} people from that company are already in this campaign",
    "customer": "works at an existing Knowella customer",
}


def _when(v) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def sequence_days(cfg: dict) -> int:
    """How long a campaign's sequence runs after the first email, in calendar days:
    its follow-up waits (business days, as Apollo counts them) plus a few days' slack."""
    from .pipeline import followup_steps
    waits = sum(int(s.get("wait_days") or 0) for s in followup_steps(cfg or {}))
    return math.ceil(waits * 7 / 5) + 3


def fmt_day(d: datetime) -> str:
    return d.strftime("%d %b %Y").lstrip("0")


class Guard:
    """The rules for adding people to one campaign, with what they need read once."""

    def __init__(self, store, campaign: str, now: datetime | None = None):
        self.store = store
        self.campaign = campaign
        self.now = now or datetime.now(timezone.utc)
        camp = store.db.campaigns.find_one({"_id": campaign}, {"owner": 1}) or {}
        self.owner = camp.get("owner") or ""
        self.customers = {d["_id"] for d in store.db.customers.find({}, {"_id": 1})}
        self._seq: dict[str, int] = {}
        self._names: dict | None = None
        self.per_company: dict[str, int] = {}
        for d in store.db.leads.find({"campaign": campaign, "company_id": {"$nin": ["", None]}}, {"company_id": 1}):
            self.per_company[d["company_id"]] = self.per_company.get(d["company_id"], 0) + 1

    def _seq_days(self, campaign: str) -> int:
        if campaign not in self._seq:
            self._seq[campaign] = sequence_days(self.store.get_campaign(campaign) or {})
        return self._seq[campaign]

    def _name(self, uid: str) -> str:
        if self._names is None:
            self._names = {d["_id"]: d.get("name") or (d.get("email") or "").split("@")[0]
                           for d in self.store.db.users.find({}, {"name": 1, "email": 1})}
        return self._names.get(uid, "") or "another rep"

    def _sent_replied(self, keys: list[str]) -> tuple[dict, dict]:
        sent = {d["_id"]: _when(d.get("created_at")) for d in self.store.db.sends.find({"_id": {"$in": keys}}, {"created_at": 1})}
        replied = {d["_id"]: _when(d.get("at")) for d in self.store.db.replies.find({"_id": {"$in": keys}}, {"at": 1})}
        return sent, replied

    def busy_until(self, enrollments: list[dict], sent: dict | None = None,
                   replied: dict | None = None) -> tuple[str, str, datetime | None]:
        """For a person's rows in OTHER campaigns: ('running'|'cooling'|'', campaign, until).
        `sent`/`replied` can be passed in pre-loaded (key -> when) for a batch."""
        if sent is None or replied is None:
            sent, replied = self._sent_replied([e["_id"] for e in enrollments])
        worst: tuple[str, str, datetime | None] = ("", "", None)
        for e in enrollments:
            k, camp = e["_id"], e.get("campaign", "")
            if k not in sent and e.get("status") in PENDING:
                pulled = _when(e.get("pulled_at"))
                if pulled and self.now - pulled < timedelta(days=PENDING_STALE_DAYS):
                    return ("running", camp, None)           # slated for contact, not sent yet
                continue                                     # left unsent for a month: abandoned
            if k not in sent:
                continue                                     # never emailed there: no cooling-off
            start = sent[k] or self.now
            end = start + timedelta(days=self._seq_days(camp))
            if k in replied:                                 # a reply stops the sequence
                end = min(end, replied[k] or start)
            if self.now < end:
                return ("running", camp, end)
            free = end + timedelta(days=COOLDOWN_DAYS)
            if self.now < free and (worst[2] is None or free > worst[2]):
                worst = ("cooling", camp, free)
        return worst

    def check(self, lead: dict, force: bool = False) -> tuple[str, str]:
        """('', '') when this lead may be added, else (code, a sentence saying why)."""
        ids = crm.identity(lead)
        if ids["domain"] and ids["domain"] in self.customers and not force:
            return "customer", f"works at {ids['domain']}, an existing Knowella customer"
        person = self.store.find_person(ids) if (ids["email"] or ids["apollo_id"] or ids["linkedin"] or ids["name_key"]) else None
        if person is not None and not force:
            for d in [person.get("company_domain")] + (self._company_domains(person.get("company_id"))):
                if d and d in self.customers:
                    return "customer", f"works at {d}, an existing Knowella customer"
            owner = person.get("owner") or ""
            if owner and owner != self.owner:
                return "owned", f"belongs to {self._name(owner)}"
            others = list(self.store.db.leads.find({"person_id": person["_id"], "campaign": {"$ne": self.campaign}},
                                                   {"campaign": 1, "status": 1, "pulled_at": 1}))
            state, camp, until = self.busy_until(others)
            if state == "running":
                return "running", (f"in campaign {camp} until {fmt_day(until)}" if until
                                   else f"already in campaign {camp} (not emailed yet)")
            if state == "cooling":
                return "cooling", f"emailed in campaign {camp}; can be added again from {fmt_day(until)}"
        cid = self._company_id(ids)
        if cid and not force and self.per_company.get(cid, 0) >= MAX_PER_COMPANY:
            if not (person and self.store.db.leads.find_one({"person_id": person["_id"], "campaign": self.campaign}, {"_id": 1})):
                return "company_cap", f"{MAX_PER_COMPANY} people from that company are already in this campaign"
        return "", ""

    def counted(self, lead: dict) -> None:
        """Note one more person added at this lead's company (for the per-company cap)."""
        cid = self._company_id(crm.identity(lead))
        if cid:
            self.per_company[cid] = self.per_company.get(cid, 0) + 1

    def _company_id(self, ids: dict) -> str:
        if ids.get("domain"):
            c = self.store.db.companies.find_one({"$or": [{"domain": ids["domain"]}, {"domains": ids["domain"]}]}, {"_id": 1})
            if c:
                return c["_id"]
        if ids.get("apollo_org_id"):
            c = self.store.db.companies.find_one({"$or": [{"apollo_org_id": ids["apollo_org_id"]},
                                                          {"apollo_org_ids": ids["apollo_org_id"]}]}, {"_id": 1})
            if c:
                return c["_id"]
        return ""

    def _company_domains(self, cid: str | None) -> list[str]:
        if not cid:
            return []
        c = self.store.db.companies.find_one({"_id": cid}, {"domain": 1, "domains": 1}) or {}
        return [c.get("domain") or ""] + list(c.get("domains") or [])

    def blocked_keys(self) -> tuple[dict[str, str], dict[str, str]]:
        """Known people the rules would refuse for this campaign, as ({Apollo id: code},
        {LinkedIn URL: code}), so a pull or a capture never pays to reveal or match them."""
        by_apollo: dict[str, str] = {}
        by_li: dict[str, str] = {}
        people = list(self.store.db.people.find(
            {"$or": [{"apollo_id": {"$exists": True}}, {"apollo_ids.0": {"$exists": True}},
                     {"linkedin_url": {"$exists": True}}]},
            {"apollo_id": 1, "apollo_ids": 1, "linkedin_url": 1, "linkedin_urls": 1, "owner": 1, "company_domain": 1}))
        rows: dict[str, list[dict]] = {}
        for d in self.store.db.leads.find({"person_id": {"$in": [p["_id"] for p in people]}, "campaign": {"$ne": self.campaign}},
                                          {"person_id": 1, "campaign": 1, "status": 1, "pulled_at": 1}):
            rows.setdefault(d["person_id"], []).append(d)
        sent, replied = self._sent_replied([e["_id"] for es in rows.values() for e in es])   # once, for everyone
        for p in people:
            if (p.get("company_domain") or "") in self.customers:
                code = "customer"
            elif (p.get("owner") or "") not in ("", self.owner):
                code = "owned"
            elif p["_id"] in rows:
                code = self.busy_until(rows[p["_id"]], sent, replied)[0]
            else:
                code = ""
            if code:
                for x in [p.get("apollo_id")] + list(p.get("apollo_ids") or []):
                    if x:
                        by_apollo[x] = code
                for x in [p.get("linkedin_url")] + list(p.get("linkedin_urls") or []):
                    if x:
                        by_li[x] = code
        return by_apollo, by_li

    def blocked_apollo_ids(self) -> set[str]:
        """Apollo person ids the rules would refuse (Apollo skips ids it's given)."""
        return set(self.blocked_keys()[0])
