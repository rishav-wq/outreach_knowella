"""MongoDB-backed store — same interface as the SQLite Store, drop-in replacement.

Selected automatically when MONGO_URI is set (see main.open_store). Keeps outreach
data in its OWN database (default 'outreach'), isolated from any product DB.

Lead `key` is used as the Mongo _id everywhere, so upserts are natural and a lead
can never be duplicated. Stage caches (research/draft/gate) match on (key, input_hash)
exactly like SQLite, so the incremental-build behavior is identical.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient

from .models import Draft, GateResult, Lead, Research


def _current_actor() -> dict:
    """Who is adding something: the signed-in user of the request being served, or the
    system for background work and the CLI. Recorded as a person's "sourced by"."""
    from . import access   # lazy: the store must not depend on the web layer at import
    u = access.current_user()
    if not u:
        return {"id": "", "email": "", "label": "system"}
    return {"id": u.get("id", ""), "email": u.get("email", ""), "label": u.get("name") or u.get("email", "")}


class MongoStore:
    def __init__(self, uri: str, db_name: str = "outreach"):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        try:
            self.client.admin.command("ping")
        except Exception as e:
            raise RuntimeError(f"Could not connect to MongoDB: {e}") from e
        self.db = self.client[db_name]
        try:
            self.ensure_indexes()
        except Exception as e:   # never block the app on an index build; say so loudly
            print(f"[indexes] WARNING: could not ensure indexes: {e}")

    def ensure_indexes(self) -> None:
        """The indexes the hot queries need. Until 12 Oct 2026 the database had none
        (`leads` had only `_id`), so every lookup by campaign, status or email scanned
        the whole collection. Idempotent: create_index is a no-op when it exists."""
        self.db.leads.create_index([("campaign", 1), ("status", 1)])
        self.db.leads.create_index([("status", 1)])
        self.db.leads.create_index([("lead.email", 1)])
        self.db.leads.create_index([("source_id", 1)], sparse=True)
        self.db.sends.create_index([("created_at", 1)])
        self.db.blast_recipients.create_index([("blast", 1)])
        self.db.blast_recipients.create_index([("email", 1)])
        self.db.llm_calls.create_index([("key", 1)])
        self.db.signals.create_index([("dedupe", 1)])
        self.db.signals.create_index([("status", 1), ("created_at", -1)])
        self.db.subscribers.create_index([("status", 1)])
        self.db.capture_tokens.create_index([("hash", 1)])
        self.db.training_state.create_index([("user", 1)])
        self.db.training_state.create_index([("key", 1)])
        self.db.training_events.create_index([("user", 1), ("at", -1)])
        self.db.training_content.create_index([("uploaded_at", -1)])
        self.db.training_signoffs.create_index([("user", 1)])
        self.db.segments.create_index([("org", 1)])
        self.db.segment_events.create_index([("segment", 1), ("at", -1)])
        # people and companies (src/crm.py). Email and domain are unique, so two imports
        # of the same person at the same moment end up as one record. The fields are left
        # out of a document when empty, which is what the partial filter relies on.
        self.db.people.create_index([("email", 1)], unique=True,
                                    partialFilterExpression={"email": {"$exists": True}})
        self.db.people.create_index([("emails", 1)], sparse=True)
        self.db.people.create_index([("apollo_ids", 1)], sparse=True)
        self.db.people.create_index([("linkedin_urls", 1)], sparse=True)
        self.db.people.create_index([("name_keys", 1)], sparse=True)
        self.db.companies.create_index([("domains", 1)], sparse=True)
        self.db.companies.create_index([("apollo_org_ids", 1)], sparse=True)
        self.db.people.create_index([("apollo_id", 1)], sparse=True)
        self.db.people.create_index([("linkedin_url", 1)], sparse=True)
        self.db.people.create_index([("name_key", 1)], sparse=True)
        self.db.people.create_index([("owner", 1)])
        self.db.people.create_index([("company_id", 1)])
        self.db.companies.create_index([("domain", 1)], unique=True,
                                       partialFilterExpression={"domain": {"$exists": True}})
        self.db.companies.create_index([("apollo_org_id", 1)], sparse=True)
        self.db.companies.create_index([("owner", 1)])
        self.db.leads.create_index([("person_id", 1)], sparse=True)
        self.db.leads.create_index([("company_id", 1)], sparse=True)
        self.db.messages.create_index([("enrollment", 1)])
        self.db.activities.create_index([("person_id", 1), ("at", -1)])
        self.db.activities.create_index([("company_id", 1), ("at", -1)])
        self.db.credit_usage.create_index([("day", 1)])     # Apollo pull allowance (src/credits.py)

    # --- campaigns (config stored in Mongo so a redeploy can never wipe it) ---
    # A campaign's whole config dict lives in one doc: {_id: slug, cfg: {...}}.
    # This replaces the old config/*.yaml files, which were baked into the image
    # and lost on every `--build` redeploy.
    def campaign_names(self) -> list[str]:
        return sorted(d["_id"] for d in self.db.campaigns.find({}, {"_id": 1}))

    def get_campaign(self, slug: str) -> dict | None:
        d = self.db.campaigns.find_one({"_id": slug})
        return d["cfg"] if d else None

    def save_campaign(self, slug: str, cfg: dict) -> None:
        # $set, not replace: the campaign doc also carries its owner (and replacing it
        # on every settings save would silently make the campaign ownerless).
        self.db.campaigns.update_one({"_id": slug}, {"$set": {"cfg": cfg}}, upsert=True)

    # --- campaign ownership (who may work in it; see access.campaign_visible) --------
    def campaign_owner(self, slug: str) -> str:
        d = self.db.campaigns.find_one({"_id": slug}, {"owner": 1})
        return (d or {}).get("owner") or ""

    def set_campaign_owner(self, slug: str, uid: str, email: str = "") -> None:
        self.db.campaigns.update_one({"_id": slug}, {"$set": {"owner": uid, "owner_email": email}})

    # --- existing Knowella customers: never in a cold campaign (src/enroll.py) ---------
    def list_customers(self) -> list[dict]:
        return list(self.db.customers.find({}).sort("_id", 1))

    def add_customers(self, domains: list[str], name: str, by: dict, source: str = "manual") -> list[str]:
        from . import crm
        added = []
        for d in domains:
            dom = crm.norm_domain(d)
            if not dom or dom in crm.FREEMAIL:
                continue
            r = self.db.customers.update_one(
                {"_id": dom}, {"$setOnInsert": {"name": name, "source": source, "by": by, "at": crm.now_iso()}}, upsert=True)
            if r.upserted_id is not None:
                added.append(dom)
        return added

    def remove_customer(self, domain: str) -> bool:
        return self.db.customers.delete_one({"_id": domain}).deleted_count == 1

    def adopt_campaign_people(self, campaign: str, owner: str, owner_email: str, by: dict) -> int:
        """When a campaign is given to someone, its leads and their companies that nobody
        owns yet become theirs (people owned by someone else stay theirs). Returns how
        many people changed hands."""
        if not owner:
            return 0
        from . import crm
        pids = self.db.leads.distinct("person_id", {"campaign": campaign, "person_id": {"$exists": True}})
        unowned = list(self.db.people.find({"_id": {"$in": pids}, "owner": {"$in": ["", None]}}, {"company_id": 1}))
        if not unowned:
            return 0
        now = crm.now_iso()
        ids = [p["_id"] for p in unowned]
        self.db.people.update_many({"_id": {"$in": ids}}, {"$set": {"owner": owner, "owner_email": owner_email, "updated_at": now}})
        cids = sorted({p.get("company_id") for p in unowned if p.get("company_id")})
        self.db.companies.update_many({"_id": {"$in": cids}, "owner": {"$in": ["", None]}},
                                      {"$set": {"owner": owner, "owner_email": owner_email, "updated_at": now}})
        for p in unowned:
            self.add_activity(p["_id"], p.get("company_id", ""), "owner_change", by,
                              f"Owner set with campaign {campaign}", meta={"from": "", "to": owner})
        return len(ids)

    def campaign_owners(self) -> dict:
        """{slug: owner user id ('' when unowned)} for every campaign."""
        return {d["_id"]: d.get("owner") or "" for d in self.db.campaigns.find({}, {"owner": 1})}

    # --- training: the playbook file (versions) and each user's saved progress --------
    def save_training_content(self, doc: dict) -> str:
        cid = uuid.uuid4().hex[:12]
        self.db.training_content.insert_one({**doc, "_id": cid})
        return cid

    def latest_training_content(self, with_html: bool = True) -> dict | None:
        proj = None if with_html else {"html": 0}
        return self.db.training_content.find_one({}, proj, sort=[("uploaded_at", -1)])

    def list_training_content(self) -> list[dict]:
        return list(self.db.training_content.find({}, {"html": 0}).sort("uploaded_at", -1))

    def training_state(self, uid: str) -> dict:
        """{key: {"value", "version"}} for one user."""
        return {d["key"]: {"value": d.get("value"), "version": d.get("version", 0)}
                for d in self.db.training_state.find({"user": uid})}

    def save_training_state(self, uid: str, email: str, key: str, value: str,
                            expected_version: int) -> int | None:
        """Write one key if it's still at expected_version. Returns the new version, or
        None when someone (another tab or device) saved since, so nothing is overwritten
        silently."""
        from pymongo.errors import DuplicateKeyError
        _id = f"{uid}:{key}"
        now = datetime.now(timezone.utc).isoformat()
        if expected_version == 0:
            try:
                self.db.training_state.insert_one({"_id": _id, "user": uid, "email": email, "key": key,
                                                   "value": value, "version": 1, "updated_at": now})
                return 1
            except DuplicateKeyError:
                return None
        r = self.db.training_state.find_one_and_update(
            {"_id": _id, "version": expected_version},
            {"$set": {"value": value, "email": email, "updated_at": now}, "$inc": {"version": 1}},
            return_document=True)
        return r["version"] if r else None

    def all_training_state(self, key: str) -> dict:
        """{user id: {"value", "updated_at"}} for one key across everyone (manager view)."""
        return {d["user"]: {"value": d.get("value"), "updated_at": d.get("updated_at", "")}
                for d in self.db.training_state.find({"key": key})}

    def add_training_events(self, uid: str, email: str, events: list[dict]) -> None:
        if events:
            now = datetime.now(timezone.utc).isoformat()
            self.db.training_events.insert_many([{**e, "user": uid, "email": email, "at": now} for e in events])

    def training_events_for(self, uid: str, limit: int = 300) -> list[dict]:
        return list(self.db.training_events.find({"user": uid}, {"_id": 0}).sort("at", -1).limit(limit))

    # Manager sign-offs live apart from the person's own progress, so a manager ticking
    # one never changes the version of an open playbook (which would make the person's
    # next save look like a clash with another tab).
    def set_signoff(self, uid: str, item: str, value: bool, by: str) -> None:
        self.db.training_signoffs.update_one(
            {"_id": f"{uid}:{item}"},
            {"$set": {"user": uid, "item": item, "value": bool(value), "by": by,
                      "at": datetime.now(timezone.utc).isoformat()}}, upsert=True)

    def signoffs_for(self, uid: str) -> dict:
        """{item: True} for the sign-offs this person has."""
        return {d["item"]: True for d in self.db.training_signoffs.find({"user": uid, "value": True})}

    def all_signoffs(self) -> dict:
        """{user id: {item: True}} across everyone (manager view)."""
        out: dict = {}
        for d in self.db.training_signoffs.find({"value": True}):
            out.setdefault(d["user"], {})[d["item"]] = True
        return out

    # --- the Target board: one shared row per industry × persona pair ------------------
    def list_segments(self, org: str) -> list[dict]:
        return list(self.db.segments.find({"org": org}))

    def get_segment(self, sid: str) -> dict | None:
        return self.db.segments.find_one({"_id": sid})

    def apply_segment_change(self, sid: str, org: str, plan: dict) -> dict | None:
        """Apply a planned change only if the row is still in the state the plan was made
        against. Returns the new row, or None when someone else changed it first (so two
        people claiming at once can't both win)."""
        from pymongo.errors import DuplicateKeyError
        exp = plan["expect"]
        q = {"_id": sid, "status": exp.get("status"), "owner": exp.get("owner")}
        upd: dict = {"$set": {**plan["set"], "org": org,
                              "updated_at": datetime.now(timezone.utc).isoformat()}}
        if plan.get("unset"):
            upd["$unset"] = plan["unset"]
        try:
            return self.db.segments.find_one_and_update(q, upd, upsert=True, return_document=True)
        except DuplicateKeyError:    # the row exists in a different state than expected
            return None

    def add_segment_event(self, sid: str, uid: str, email: str, action: str, detail: dict) -> None:
        self.db.segment_events.insert_one({"segment": sid, "user": uid, "email": email, "action": action,
                                           "detail": detail, "at": datetime.now(timezone.utc).isoformat()})

    # --- users: everyone who has signed in, with their role ---------------------------
    def get_user(self, uid: str) -> dict | None:
        return self.db.users.find_one({"_id": uid}) if uid else None

    def ensure_user(self, uid: str, email: str, name: str, role: str, active: bool = True) -> dict:
        """First sign-in creates the user with `role` (and `active`); afterwards the stored
        values win. Email and name follow Clerk, so a renamed account shows its current name."""
        from pymongo.errors import DuplicateKeyError
        now = datetime.now(timezone.utc).isoformat()
        try:
            self.db.users.update_one(
                {"_id": uid},
                {"$setOnInsert": {"role": role, "active": bool(active), "created_at": now},
                 "$set": {"email": (email or "").strip().lower(), "name": name or ""}},
                upsert=True)
        except DuplicateKeyError:   # two first requests at once; the other one created it
            pass
        return self.db.users.find_one({"_id": uid})

    def list_users(self) -> list[dict]:
        return list(self.db.users.find({}).sort("created_at", 1))

    def update_user(self, uid: str, fields: dict) -> dict | None:
        clean = {k: v for k, v in fields.items() if k in ("role", "active")}
        if clean:
            clean["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.db.users.update_one({"_id": uid}, {"$set": clean})
        return self.get_user(uid)

    def touch_user(self, uid: str) -> None:
        """Record last activity, at most once a minute per user (it runs on every request)."""
        now = datetime.now(timezone.utc)
        cutoff = (now.replace(microsecond=0)).isoformat()[:16]   # minute resolution
        self.db.users.update_one({"_id": uid, "last_seen_min": {"$ne": cutoff}},
                                 {"$set": {"last_seen": now.isoformat(), "last_seen_min": cutoff}})

    def delete_campaign(self, slug: str) -> None:
        self.db.campaigns.delete_one({"_id": slug})

    def campaign_exists(self, slug: str) -> bool:
        return self.db.campaigns.count_documents({"_id": slug}, limit=1) > 0

    def has_any_campaign(self) -> bool:
        return self.db.campaigns.count_documents({}, limit=1) > 0

    # --- leads ---------------------------------------------------------------
    @staticmethod
    def _base_key(lead: Lead) -> str:
        """The lead's identity WITHOUT any campaign prefix — email, else name|domain.
        Deliberately ignores stored_key so re-upserting a loaded (already-scoped) lead
        never double-prefixes."""
        return (lead.email or f"{lead.full_name}|{lead.company_domain}").strip().lower()

    @staticmethod
    def _scoped(campaign: str, base: str) -> str:
        return f"{campaign}::{base}"

    def upsert_lead(self, lead: Lead, campaign: str, topics: list | None = None,
                    source_id: str = "", guard=None, force: bool = False) -> tuple[str, str]:
        """Add a lead to a campaign. Returns ('', '') when added (or already there), else
        (code, why) when the campaign rules refuse them (src/enroll.py): already in a
        running campaign, cooling off, another rep's lead, the company's cap, or an
        existing customer. Pass one `guard` (enroll.Guard) for a whole batch; `force`
        (admins, from the Library) skips the rules."""
        # _id is campaign-scoped so the SAME person can live in multiple campaigns as
        # independent rows (own research/draft/status). Re-importing into the SAME
        # campaign still dedups (same _id, $setOnInsert no-ops).
        sid = self._scoped(campaign, self._base_key(lead))
        doc = {"campaign": campaign, "status": "new", "lead": lead.model_dump(),
               "topics": topics or [], "pulled_at": datetime.now(timezone.utc)}
        if source_id:      # which LinkedIn group / publication / community produced them
            doc["source_id"] = source_id
        if self.db.leads.find_one({"_id": sid}, {"_id": 1}) is None:
            from . import enroll
            guard = guard or enroll.Guard(self, campaign)
            code, why = guard.check(doc["lead"], force=force)
            if code:
                return code, why
            guard.counted(doc["lead"])
        r = self.db.leads.update_one({"_id": sid}, {"$setOnInsert": doc}, upsert=True)
        # Every lead row is also a person (and usually a company). A failure here must not
        # lose the import, so it's logged; `python -m src.backfill_people --apply` links
        # anything left unlinked.
        try:
            self.link_person(doc["lead"], sid, campaign, by=_current_actor(),
                             enrolled=r.upserted_id is not None)
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("uvicorn.error").error("[crm] couldn't link %s to a person: %s", sid, e)
        return "", ""

    def migrate_lead_keys(self) -> int:
        """One-time: re-key legacy leads (_id = base email) to campaign-scoped ids
        (_id = 'campaign::base'), moving each lead's per-lead stage data with it, so
        the same person can live in multiple campaigns. Idempotent — already-scoped
        docs (id contains '::') are skipped, so it's safe to run on every startup."""
        moved = 0
        for d in list(self.db.leads.find({"_id": {"$not": {"$regex": "::"}}})):
            old = d["_id"]
            campaign = d.get("campaign") or ""
            new = self._scoped(campaign, old)
            if new == old or self.db.leads.find_one({"_id": new}):
                continue
            self.db.leads.insert_one({**d, "_id": new})
            # per-lead stage data keyed by _id → copy under the new id, drop the old
            for coll in (self.db.research, self.db.drafts, self.db.gate, self.db.outbox,
                         self.db.reviews, self.db.sends, self.db.meetings, self.db.replies):
                sd = coll.find_one({"_id": old})
                if sd:
                    if not coll.find_one({"_id": new}):
                        coll.insert_one({**sd, "_id": new})
                    coll.delete_one({"_id": old})
            self.db.llm_calls.update_many({"key": old}, {"$set": {"key": new}})   # keyed by a `key` field
            self.db.leads.delete_one({"_id": old})
            moved += 1
        return moved

    def all_leads(self, status: str | None = None) -> list[dict]:
        """Lead summaries across all campaigns, optionally filtered by status.

        The library passes status='excluded' — the bench of leads removed from
        campaigns (never deleted, only flipped to 'excluded' with drafts cleared),
        kept for reuse. Returns raw rows; the API adds function bucket + topics.
        """
        q = {"status": status} if status else {}
        # projection + raw dicts, no Pydantic: the library lists thousands of rows and
        # only needs these eight fields — full-document validation made the tab crawl
        proj = {"campaign": 1, "status": 1, "topics": 1, "lead.first_name": 1,
                "lead.last_name": 1, "lead.title": 1, "lead.company": 1,
                "lead.email": 1, "lead.source": 1}
        out = []
        for d in self.db.leads.find(q, proj):
            L = d.get("lead") or {}
            out.append({"key": d["_id"], "campaign": d.get("campaign", ""),
                        "status": d.get("status", ""), "topics": d.get("topics") or [],
                        "name": f"{L.get('first_name', '')} {L.get('last_name', '')}".strip(),
                        "title": L.get("title", ""), "company": L.get("company", ""),
                        "email": L.get("email", ""), "source": L.get("source", "")})
        return out

    def exclude_lead(self, key: str) -> None:
        """Drop a lead from its campaign's pipeline without losing the lead.

        Clears the campaign-specific generated work (drafts/follow-ups in the
        outbox + the review decision) and flips status to 'excluded' so it leaves
        Review and is skipped by the pipeline — but the lead row and its cached
        research stay, so it remains in the library for future marketing.
        """
        self.db.leads.update_one({"_id": key}, {"$set": {"status": "excluded"}})
        self.db.outbox.delete_one({"_id": key})
        self.db.reviews.delete_one({"_id": key})

    def exclude_leads(self, keys: list[str]) -> int:
        """Bulk exclude — same as exclude_lead for each key (kept in the library).
        Returns how many leads were affected."""
        if not keys:
            return 0
        self.db.leads.update_many({"_id": {"$in": keys}}, {"$set": {"status": "excluded"}})
        self.db.outbox.delete_many({"_id": {"$in": keys}})
        self.db.reviews.delete_many({"_id": {"$in": keys}})
        return len(keys)

    def delete_leads(self, keys: list[str]) -> int:
        """Permanently delete leads and ALL their per-lead data — gone everywhere,
        including the library. For junk pulls with no reuse value. The global
        do-not-contact list is NOT touched (compliance outlives any single lead);
        the email-keyed verify cache is left alone (shared, not per-lead).
        Returns how many lead rows were removed."""
        if not keys:
            return 0
        q = {"_id": {"$in": keys}}
        res = self.db.leads.delete_many(q)
        # all per-lead stage data is keyed by the lead key as _id …
        for coll in (self.db.outbox, self.db.reviews, self.db.research, self.db.drafts,
                     self.db.gate, self.db.sends, self.db.meetings, self.db.replies):
            coll.delete_many(q)
        self.db.llm_calls.delete_many({"key": {"$in": keys}})   # … except llm_calls, keyed by a `key` field
        return res.deleted_count

    def set_status(self, key: str, status: str) -> None:
        upd: dict = {"$set": {"status": status}}
        if status != "error":
            upd["$unset"] = {"error": ""}   # a success clears the stale failure reason
        self.db.leads.update_one({"_id": key}, upd)

    def update_lead(self, lead: Lead) -> None:
        self.db.leads.update_one({"_id": lead.key}, {"$set": {"lead": lead.model_dump()}})

    def get_lead(self, key: str) -> Lead | None:
        d = self.db.leads.find_one({"_id": key})
        if not d:
            return None
        lead = Lead.model_validate(d["lead"])
        lead.stored_key = key
        return lead

    def leads(self, campaign: str, status: str | None = None,
              include_raw: bool = True) -> list[Lead]:
        """include_raw=False leaves out the raw Apollo payload (tens of KB a person)
        for callers that only show or check name, title, company and email."""
        q = {"campaign": campaign}
        if status:
            q["status"] = status
        out = []
        for d in self.db.leads.find(q, None if include_raw else {"lead.raw": 0}):
            lead = Lead.model_validate(d["lead"])
            lead.stored_key = d["_id"]
            out.append(lead)
        return out

    def counts(self, campaign: str) -> dict:
        agg = self.db.leads.aggregate([
            {"$match": {"campaign": campaign}},
            {"$group": {"_id": "$status", "c": {"$sum": 1}}},
        ])
        return {d["_id"]: d["c"] for d in agg}

    def lead_summaries(self, campaign: str) -> list[dict]:
        # projection + raw dicts, no Pydantic — this backs the Leads tab AND the
        # Inbox's lead directory, both of which list hundreds of rows
        proj = {"status": 1, "error": 1, "pulled_at": 1, "lead.first_name": 1,
                "lead.last_name": 1, "lead.title": 1, "lead.company": 1,
                "lead.email": 1, "lead.source": 1, "lead.raw.id": 1,
                "lead.linkedin_url": 1}
        out = []
        for d in self.db.leads.find({"campaign": campaign}, proj):
            L = d.get("lead") or {}
            out.append({"key": d["_id"], "status": d.get("status", ""),
                        "name": f"{L.get('first_name', '')} {L.get('last_name', '')}".strip(),
                        "company": L.get("company", ""), "title": L.get("title", ""),
                        "email": L.get("email", ""), "source": L.get("source", ""),
                        # why the last pipeline attempt failed ('' when it didn't)
                        "error": d.get("error") or "",
                        # when the lead was first pulled in (None for leads pulled before this was tracked)
                        "pulled_at": d["pulled_at"].isoformat() if d.get("pulled_at") else None,
                        # Apollo person id — lets the UI offer "find more like this" (lookalike seed)
                        "apollo_id": (L.get("raw") or {}).get("id") or "",
                        # Apollo has returned this on every person since the first pull;
                        # it was simply never projected. It is the fastest way to sanity-
                        # check a row before mailing it — a title from an enrichment feed
                        # is a claim, the profile is the thing you can look at.
                        "linkedin_url": L.get("linkedin_url") or ""})
        return out

    def save_lead_error(self, key: str, reason: str) -> None:
        """Persist WHY a lead errored, so mass failures are diagnosable after the fact."""
        self.db.leads.update_one({"_id": key}, {"$set": {"error": reason}})

    # --- people and companies (one record each; see src/crm.py) --------------------
    # Identity keys are never overwritten. The first value seen stays in the main field;
    # any other value seen for the same record is added to its plural list (emails,
    # apollo_ids, linkedin_urls, name_keys / domains, apollo_org_ids), and lookups check
    # both. Overwriting made a company's Apollo id flip between two values (one company,
    # two Apollo records), so a later row missed it and created a duplicate.
    _PERSON_KEYS = (("apollo_id", "apollo_ids"), ("linkedin_url", "linkedin_urls"), ("name_key", "name_keys"))
    _COMPANY_KEYS = (("domain", "domains"), ("apollo_org_id", "apollo_org_ids"))

    @staticmethod
    def _either(field: str, plural: str, value: str) -> dict:
        return {"$or": [{field: value}, {plural: value}]}

    def find_person(self, ids: dict) -> dict | None:
        """The existing person for these identity keys, strongest key first. A name at a
        domain is only used for someone with no email: two different people can share a
        name at a company, and their emails tell them apart."""
        if ids.get("email"):
            d = self.db.people.find_one(self._either("email", "emails", ids["email"]))
            if d:
                return d
        for field, plural, key in (("apollo_id", "apollo_ids", "apollo_id"),
                                   ("linkedin_url", "linkedin_urls", "linkedin")):
            if ids.get(key):
                d = self.db.people.find_one(self._either(field, plural, ids[key]))
                if d:
                    return d
        if not ids.get("email") and ids.get("name_key"):
            return self.db.people.find_one({**self._either("name_key", "name_keys", ids["name_key"]),
                                            "email": {"$exists": False}})
        return None

    @staticmethod
    def _keep_keys(existing: dict, fields: dict, keys: tuple) -> tuple[dict, dict]:
        """Split new values for identity keys: set where the record has none yet, else
        add to the plural list when different. Returns ($set part, $addToSet part)."""
        sets, adds = {}, {}
        for field, plural in keys:
            v = fields.pop(field, None)
            if not v:
                continue
            if not existing.get(field):
                sets[field] = v
            elif existing[field] != v and v not in (existing.get(plural) or []):
                adds[plural] = v
        return sets, adds

    def _link_company(self, lead: dict, ids: dict, owner: str, owner_email: str, now: str) -> str:
        from pymongo import ReturnDocument
        from . import crm
        fields = crm.company_fields(lead)
        existing = None
        if ids.get("domain"):
            existing = self.db.companies.find_one(self._either("domain", "domains", ids["domain"]))
        if existing is None and ids.get("apollo_org_id"):
            existing = self.db.companies.find_one(self._either("apollo_org_id", "apollo_org_ids", ids["apollo_org_id"]))
        if existing is not None:
            sets, adds = self._keep_keys(existing, fields, self._COMPANY_KEYS)
            upd: dict = {"$set": {**fields, **sets, "updated_at": now}}
            if adds:
                upd["$addToSet"] = adds
            self.db.companies.update_one({"_id": existing["_id"]}, upd)
            return existing["_id"]
        if not ids.get("domain") and not ids.get("apollo_org_id"):
            return ""
        doc = {"_id": crm.new_id(), **fields, "owner": owner, "owner_email": owner_email,
               "stage": "", "created_at": now, "updated_at": now}
        if ids.get("domain"):
            got = self.db.companies.find_one_and_update(
                {"domain": ids["domain"]}, {"$setOnInsert": doc}, upsert=True,
                return_document=ReturnDocument.AFTER)
            return got["_id"]
        self.db.companies.insert_one(doc)
        return doc["_id"]

    def upsert_person(self, lead: dict, owner: str, owner_email: str, by: dict, when: str,
                      source_campaign: str = "") -> tuple[str, str, bool]:
        """Find or create the person (and their company) for a lead-shaped dict.
        Returns (person id, company id, created). An existing person gets refreshed
        Apollo fields and any new identity values; their owner, stage, notes and
        interests are never touched. ('', '', False) when nothing identifies a person."""
        from pymongo import ReturnDocument
        from . import crm
        ids = crm.identity(lead)
        if not (ids["email"] or ids["apollo_id"] or ids["linkedin"] or ids["name_key"]):
            return "", "", False
        now = crm.now_iso()
        company_id = self._link_company(lead, ids, owner, owner_email, now)
        fields = crm.person_fields(lead)
        if company_id:
            fields["company_id"] = company_id
        existing = self.find_person(ids)
        if existing is not None:
            sets, adds = self._keep_keys(existing, fields, self._PERSON_KEYS)
            if ids["email"] and ids["email"] != existing.get("email"):
                if not existing.get("email"):
                    sets["email"] = ids["email"]
                elif ids["email"] not in (existing.get("emails") or []):
                    adds["emails"] = ids["email"]                # same person, another address
            upd: dict = {"$set": {**fields, **sets, "updated_at": now}}
            if adds:
                upd["$addToSet"] = adds
            self.db.people.update_one({"_id": existing["_id"]}, upd)
            return existing["_id"], company_id, False
        doc = {"_id": crm.new_id(), **fields,
               "source": {"type": crm.source_type(lead.get("source", "")), "campaign": source_campaign},
               "sourced_by": {**by, "at": when},
               "owner": owner, "owner_email": owner_email, "stage": "", "interests": [],
               "phones": [], "created_at": when, "updated_at": now}
        if ids["email"]:
            doc["email"] = ids["email"]
            got = self.db.people.find_one_and_update(
                {"email": ids["email"]}, {"$setOnInsert": doc}, upsert=True,
                return_document=ReturnDocument.AFTER)
            return got["_id"], company_id, got["_id"] == doc["_id"]
        self.db.people.insert_one(doc)
        return doc["_id"], company_id, True

    def add_activity(self, person_id: str, company_id: str, kind: str, by: dict, body: str = "",
                     at: str | None = None, **extra) -> dict:
        """One timeline entry. ObjectId ids are time-ordered, so same-instant events keep
        their order."""
        from . import crm
        doc = {"_id": ObjectId(), "person_id": person_id, "company_id": company_id, "type": kind,
               "by": by, "at": crm.now_iso() if at is None else at, "body": body, **extra}
        self.db.activities.insert_one(doc)
        return doc

    def link_person(self, lead: dict, enrollment_id: str, campaign: str, by: dict | None = None,
                    enrolled: bool = True, at: str | None = None) -> str:
        """Find or create the person (and company) behind one lead row, and point the row
        at them. Idempotent: linking the same row again changes nothing but the
        refreshed Apollo fields. Returns the person id ('' when the row has nothing to
        identify a person by).

        A new person is owned by the owner of the campaign they arrived through (the one
        who works that campaign); an existing person keeps their owner, stage, notes and
        interests. `at` backdates the timeline entries (the backfill uses the pull date)."""
        from . import crm
        when = crm.now_iso() if at is None else at   # "" = date unknown (rows pulled before dates were kept)
        by = by or {"id": "", "email": "", "label": "system"}
        camp = self.db.campaigns.find_one({"_id": campaign}, {"owner": 1, "owner_email": 1}) or {}
        pid, company_id, created = self.upsert_person(lead, camp.get("owner") or "", camp.get("owner_email") or "",
                                                       by, when, source_campaign=campaign)
        if not pid:
            return ""
        if not created and camp.get("owner"):   # an unowned person joining someone's campaign becomes theirs
            r = self.db.people.update_one({"_id": pid, "owner": {"$in": ["", None]}},
                                          {"$set": {"owner": camp["owner"], "owner_email": camp.get("owner_email") or ""}})
            if r.modified_count:
                self.add_activity(pid, company_id, "owner_change", by, f"Owner set with campaign {campaign}",
                                  at=when, meta={"from": "", "to": camp["owner"]})
        prev = self.db.leads.find_one_and_update(
            {"_id": enrollment_id}, {"$set": {"person_id": pid, "company_id": company_id}},
            projection={"person_id": 1})
        newly_linked = bool(prev) and prev.get("person_id") != pid
        if created:
            self.add_activity(pid, company_id, "created", by,
                              f"Added from {crm.source_type(lead.get('source', '')) or 'an import'}",
                              at=when, campaign=campaign, enrollment=enrollment_id)
        if enrolled and newly_linked:
            self.add_activity(pid, company_id, "enrolled", by, f"Added to campaign {campaign}",
                              at=when, campaign=campaign, enrollment=enrollment_id)
        return pid

    # --- research (cached by input_hash) ------------------------------------
    def get_research(self, key: str, input_hash: str) -> Research | None:
        d = self.db.research.find_one({"_id": key, "input_hash": input_hash})
        return Research.model_validate(d["data"]) if d else None

    def get_research_any(self, key: str) -> Research | None:
        """Latest stored research for a lead, ignoring input_hash — for display."""
        d = self.db.research.find_one({"_id": key})
        return Research.model_validate(d["data"]) if d else None

    def save_research(self, key: str, input_hash: str, research: Research) -> None:
        self.db.research.replace_one(
            {"_id": key}, {"_id": key, "input_hash": input_hash, "data": research.model_dump()}, upsert=True
        )

    # --- drafts (cached by input_hash) --------------------------------------
    def get_draft(self, key: str, input_hash: str) -> Draft | None:
        d = self.db.drafts.find_one({"_id": key, "input_hash": input_hash})
        return Draft.model_validate(d["data"]) if d else None

    def save_draft(self, key: str, input_hash: str, draft: Draft) -> None:
        self.db.drafts.replace_one(
            {"_id": key}, {"_id": key, "input_hash": input_hash, "data": draft.model_dump()}, upsert=True
        )

    # --- gate (cached by the draft's input_hash) ----------------------------
    def get_gate(self, key: str, input_hash: str) -> GateResult | None:
        d = self.db.gate.find_one({"_id": key, "input_hash": input_hash})
        return GateResult.model_validate(d["data"]) if d else None

    def save_gate(self, key: str, input_hash: str, gate: GateResult) -> None:
        self.db.gate.replace_one(
            {"_id": key},
            {"_id": key, "input_hash": input_hash, "verdict": gate.verdict,
             "reason": gate.reason, "data": gate.model_dump()},
            upsert=True,
        )

    # --- sends (idempotency) -------------------------------------------------
    def is_sent(self, key: str) -> bool:
        return self.db.sends.find_one({"_id": key}) is not None

    # --- per-mailbox daily send counter -------------------------------------
    # The app had no idea how much each mailbox had sent today, so a hash-based
    # rotation blew past Apollo's caps (75/70) and kept feeding mailboxes Apollo
    # had already flagged Unhealthy. This is the ledger that makes caps real.
    def bump_mailbox_send(self, mailbox_id: str) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.db.mailbox_sends.update_one(
            {"_id": f"{day}::{mailbox_id}"},
            {"$inc": {"n": 1}, "$set": {"day": day, "mailbox": mailbox_id}},
            upsert=True)

    def mailbox_sends_today(self) -> dict:
        """{mailbox_id: count} for today (UTC)."""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {d["mailbox"]: d.get("n", 0) for d in self.db.mailbox_sends.find({"day": day})}

    def mark_sent(self, key: str, platform: str, platform_id: str = "") -> None:
        self.db.sends.update_one(
            {"_id": key},
            {"$setOnInsert": {"platform": platform, "platform_id": platform_id,
                              "created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def sent_today(self, campaign: str) -> int:
        """Sends recorded today (UTC) for this campaign — drives the daily cap.
        Sends written before timestamps existed have no created_at and don't count."""
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        keys = [d["_id"] for d in self.db.leads.find({"campaign": campaign}, {"_id": 1})]
        if not keys:
            return 0
        return self.db.sends.count_documents({"_id": {"$in": keys}, "created_at": {"$gte": start}})

    def sent_in_other_campaign(self, key: str) -> bool:
        """True if this lead's base identity (the part after 'campaign::') was already
        SENT in a DIFFERENT campaign — powers opt-in cross-campaign dedup so the same
        person isn't emailed twice across campaigns. Keyed by base so it matches the
        same person even when they live as separate rows in each campaign."""
        if "::" not in key:
            return False
        campaign, base = key.split("::", 1)
        for d in self.db.sends.find({"_id": {"$regex": "::" + re.escape(base) + "$"}}, {"_id": 1}):
            if not d["_id"].startswith(campaign + "::"):
                return True
        return False

    # --- cost audit ----------------------------------------------------------
    def log_llm(self, key: str, stage: str, model: str, usage: dict) -> None:
        if not usage:
            return
        self.db.llm_calls.insert_one({
            "key": key, "stage": stage, "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        })

    def token_totals(self, campaign: str) -> dict:
        keys = [d["_id"] for d in self.db.leads.find({"campaign": campaign}, {"_id": 1})]
        agg = list(self.db.llm_calls.aggregate([
            {"$match": {"key": {"$in": keys}}},
            {"$group": {"_id": None, "p": {"$sum": "$prompt_tokens"}, "c": {"$sum": "$completion_tokens"}}},
        ]))
        return {"prompt_tokens": agg[0]["p"] if agg else 0, "completion_tokens": agg[0]["c"] if agg else 0}

    # --- outbox --------------------------------------------------------------
    def save_outbox(self, key: str, draft, verdict: str, variant: str = "signal") -> None:
        self.db.outbox.replace_one(
            {"_id": key},
            {"_id": key, "subject": draft.subject, "body": draft.body, "angle": draft.angle,
             "verdict": verdict, "edited": False, "variant": variant},
            upsert=True,
        )

    @staticmethod
    def _shape_outbox(d: dict) -> dict:
        out = {"subject": d["subject"], "body": d["body"], "angle": d.get("angle", ""),
               "verdict": d["verdict"], "edited": bool(d.get("edited", False)),
               "variant": d.get("variant", "signal"), "fu_hash": d.get("fu_hash", "")}
        for k, v in d.items():
            if (k.startswith("subject_") or k.startswith("body_")) and k.rsplit("_", 1)[-1].isdigit():
                out[k] = v or ""
        return out

    def get_outboxes(self, keys: list[str]) -> dict:
        """{key: shaped outbox} in ONE query — per-key lookups over a remote Mongo
        turned the Review/Inbox tabs into thousands of sequential round trips."""
        if not keys:
            return {}
        return {d["_id"]: self._shape_outbox(d) for d in self.db.outbox.find({"_id": {"$in": keys}})}

    def get_reviews(self, keys: list[str]) -> dict:
        if not keys:
            return {}
        return {d["_id"]: d.get("decision", "") for d in self.db.reviews.find({"_id": {"$in": keys}})}

    def get_verifies(self, emails: list[str]) -> dict:
        if not emails:
            return {}
        return {d["_id"]: d.get("status", "") for d in self.db.verify.find({"_id": {"$in": emails}})}

    def get_research_facts(self, keys: list[str]) -> dict:
        """{key: [raw fact dicts]} in one query, no Pydantic — display only."""
        if not keys:
            return {}
        out = {}
        for d in self.db.research.find({"_id": {"$in": keys}}, {"data.facts": 1}):
            out[d["_id"]] = ((d.get("data") or {}).get("facts")) or []
        return out

    def get_outbox(self, key: str) -> dict | None:
        d = self.db.outbox.find_one({"_id": key})
        if not d:
            return None
        out = {"subject": d["subject"], "body": d["body"], "angle": d.get("angle", ""),
               "verdict": d["verdict"], "edited": bool(d.get("edited", False)),
               "variant": d.get("variant", "signal"), "fu_hash": d.get("fu_hash", "")}
        # every follow-up step present (subject_2/body_2, subject_3/body_3, … any count)
        for k, v in d.items():
            if (k.startswith("subject_") or k.startswith("body_")) and k.rsplit("_", 1)[-1].isdigit():
                out[k] = v or ""
        return out

    def update_outbox(self, key: str, subject: str, body: str) -> None:
        self.db.outbox.update_one({"_id": key}, {"$set": {"subject": subject, "body": body, "edited": True}})

    def save_followups(self, key: str, followups: list[dict], fu_hash: str) -> None:
        """The lead's follow-up emails (sequence steps 2..N, any count) — replaces the
        whole set: followups = [{'subject','body'}] in step order. fu_hash caches against
        the first draft + step templates so they regenerate when either changes. Steps
        left over from a previously longer sequence are removed."""
        doc = self.db.outbox.find_one({"_id": key}) or {}
        new: dict = {"fu_hash": fu_hash}
        for i, f in enumerate(followups, start=2):
            new[f"subject_{i}"] = f.get("subject", "")
            new[f"body_{i}"] = f.get("body", "")
        stale = [k for k in doc
                 if (k.startswith("subject_") or k.startswith("body_"))
                 and k.rsplit("_", 1)[-1].isdigit() and int(k.rsplit("_", 1)[-1]) >= len(followups) + 2]
        update: dict = {"$set": new}
        if stale:
            update["$unset"] = {k: "" for k in stale}
        self.db.outbox.update_one({"_id": key}, update)

    def update_followup(self, key: str, step: int, subject: str, body: str) -> None:
        """Manual edit of one follow-up (step 2 or 3)."""
        self.db.outbox.update_one({"_id": key}, {"$set": {
            f"subject_{step}": subject, f"body_{step}": body, "edited": True}})

    def rename_campaign(self, old: str, new: str) -> int:
        """Re-key every lead from one campaign name to another. Returns leads moved."""
        return self.db.leads.update_many({"campaign": old}, {"$set": {"campaign": new}}).modified_count

    # --- marketing: audiences resolved live from the Library, blasts via Postmark ---
    # Projections for the audience pass. A full lead document carries the raw Apollo
    # payload, tens of KB a person. Loading and validating every one of them on each
    # filter change (the composer re-asks 350 ms after every click, and the Audiences
    # page asks once per saved audience) is what ran the 2 GB production VM out of
    # memory in October 2026. Nothing an audience renders reads it: merge fields use
    # name, company, title and email only (personalize._placeholder_map).
    _AUD_COUNT_PROJ = {"campaign": 1, "status": 1, "topics": 1, "lead.email": 1}
    _AUD_FULL_PROJ = {"lead.raw": 0}

    def audience_leads(self, flt: dict) -> list[dict]:
        """Resolve an audience filter against the WHOLE Library, deduped by email.

        flt: {topics: [..] any-match, statuses: [..], exclude_sent: bool,
        engagement: ''|'opened'|'clicked'}. Emailless and suppressed people never make
        it in. exclude_sent drops anyone the sales engine has already emailed in ANY
        campaign (the 'never pitched' audience); engagement narrows to people who
        opened/clicked a previous blast — the warm slice.
        Returns [{email, key, lead}] — lead is the Lead for merge rendering (without
        its raw source payload)."""
        return list(self._iter_audience(flt, with_lead=True))

    def audience_count(self, flt: dict) -> int:
        """How many people audience_leads would return, without building any of them."""
        return sum(1 for _ in self._iter_audience(flt, with_lead=False))

    def audience_sample(self, flt: dict, n: int) -> list[dict]:
        """The first n people audience_leads would return (same order), stopping early."""
        out: list[dict] = []
        if n <= 0:
            return out
        for p in self._iter_audience(flt, with_lead=True):
            out.append(p)
            if len(out) >= n:
                break
        return out

    def _iter_audience(self, flt: dict, with_lead: bool):
        """Yield {email, key, lead} per person an audience reaches, in send order.

        The ONE implementation behind the count, the preview and the send, so a screen
        can never show a number the send disagrees with. lead is a Lead when
        with_lead, else None (the count path never builds one)."""
        # subscribers_only is a different question from every other filter: not
        # "who in the Library matches" but "who actually asked for this". It is the
        # only audience a newsletter may legally and safely go to, so it short-
        # circuits the Library entirely rather than narrowing it.
        if flt.get("subscribers_only"):
            sup = self.suppressed_set()
            # An issue reaches a subscriber when what they asked for overlaps what
            # this publication covers. No topics chosen means everything — the honest
            # reading of somebody who subscribed without ticking a box.
            want = set(flt.get("publication_topics") or [])
            subs = []
            for d in self.list_subscribers("confirmed"):
                if self._is_sup(d["_id"], sup):
                    continue
                mine = set(d.get("topics") or [])
                if want and mine and not (want & mine):
                    continue
                subs.append(d)
            # One Library lookup for all of them. lead_by_email per subscriber was a
            # case-insensitive regex, i.e. a full collection scan per person.
            lead_docs = self._leads_by_emails([d["_id"] for d in subs]) if with_lead else {}
            for d in subs:
                email = d["_id"]
                lead = None
                if with_lead:
                    ld = lead_docs.get(email)
                    lead = (Lead.model_validate(ld) if ld is not None else
                            Lead(first_name=(d.get("name") or "").split(" ")[0], email=email))
                yield {"email": email, "key": f"sub::{email}", "lead": lead}
            return

        topics = set(flt.get("topics") or [])
        # Campaign is the coarsest cut there is, and it was the one filter missing:
        # a Freight Paperwork issue resolved to the whole 4,735-person Library,
        # venture and private-equity contacts included. Any-match, like topics —
        # a lead sits in one campaign per document, and the Library is the union.
        campaigns = set(flt.get("campaigns") or [])
        statuses = set(flt.get("statuses") or [])
        want_eng = flt.get("engagement") or ""
        engaged = self.engagement_by_email() if want_eng else {}
        sup = self.suppressed_set()
        # Deliberately queried across EVERY campaign, not just the selected ones.
        # "Skip anyone sales already emailed" means anyone, anywhere — narrowing it
        # to the chosen campaigns would let a freight blast land on someone a
        # different campaign cold-emailed yesterday. Projected rather than validated:
        # this only needs the address, and it runs over the whole collection.
        sent_emails = set()
        if flt.get("exclude_sent"):
            sent_emails = {((d.get("lead") or {}).get("email") or "").strip().lower()
                           for d in self.db.leads.find({"status": "sent"}, {"lead.email": 1})}
            sent_emails.discard("")
        q = {"campaign": {"$in": list(campaigns)}} if campaigns else {}
        proj = self._AUD_FULL_PROJ if with_lead else self._AUD_COUNT_PROJ
        seen: set[str] = set()
        # Natural order, as before the indexes existed: when one person sits in two
        # campaigns, the row a send uses must not change because a query plan did.
        for d in self.db.leads.find(q, proj).hint([("$natural", 1)]):
            L = d.get("lead") or {}
            email = (L.get("email") or "").strip().lower()
            if not email or email in seen or email in sent_emails:
                continue
            if topics and not (topics & set(d.get("topics") or [])):
                continue
            if statuses and d.get("status") not in statuses:
                continue
            if want_eng and not engaged.get(email, {}).get(want_eng):
                continue
            if self._is_sup(email, sup):
                continue
            seen.add(email)
            yield {"email": email, "key": d["_id"],
                   "lead": Lead.model_validate(L) if with_lead else None}

    def _leads_by_emails(self, emails: list[str]) -> dict:
        """{lowercased email: lead dict without raw} for the first Library row per
        address in natural order — lead_by_email for many addresses at once, in two
        projected queries instead of one collection scan each."""
        want = {(e or "").lower() for e in emails if e}
        if not want:
            return {}
        first: dict[str, str] = {}
        for d in self.db.leads.find({}, {"lead.email": 1}).hint([("$natural", 1)]):
            e = ((d.get("lead") or {}).get("email") or "").lower()
            if e in want and e not in first:
                first[e] = d["_id"]
        if not first:
            return {}
        by_id = {d["_id"]: d.get("lead") or {} for d in
                 self.db.leads.find({"_id": {"$in": list(first.values())}}, self._AUD_FULL_PROJ)}
        return {e: by_id[i] for e, i in first.items() if i in by_id}

    def lead_by_email(self, email: str) -> Lead | None:
        """A subscriber who is also in the Library gets their real merge fields —
        first name, company, title — instead of an empty shell."""
        d = self.db.leads.find_one({"lead.email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        return Lead.model_validate(d["lead"]) if d else None

    # --- email images ---------------------------------------------------------
    # Kept in Mongo rather than on disk deliberately: the app runs from a container
    # that is rebuilt on every deploy, and an image referenced by mail already sent
    # must not disappear because somebody shipped a fix. Content-addressed, so the
    # same logo pasted into ten issues is stored once and never goes stale.
    def put_asset(self, data: bytes, content_type: str) -> str:
        import hashlib
        h = hashlib.sha256(data).hexdigest()[:32]
        self.db.email_assets.update_one(
            {"_id": h},
            {"$setOnInsert": {"_id": h, "data": data, "content_type": content_type,
                              "bytes": len(data),
                              "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True)
        return h

    # Named assets: the logo and the social icons are the SAME image in every issue,
    # so re-uploading them per newsletter is work that exists only because nothing
    # remembered them. A name is a stable handle; the hash underneath can change when
    # a new logo is uploaded, and every future issue picks it up without being edited.
    def name_asset(self, name: str, h: str) -> None:
        n = (name or "").strip().lower()
        if n:
            self.db.asset_names.replace_one(
                {"_id": n}, {"_id": n, "hash": h,
                             "updated_at": datetime.now(timezone.utc).isoformat()}, upsert=True)

    def asset_by_name(self, name: str) -> str:
        d = self.db.asset_names.find_one({"_id": (name or "").strip().lower()})
        return (d or {}).get("hash", "")

    def named_assets(self) -> list[dict]:
        out = []
        for d in self.db.asset_names.find().sort("_id", 1):
            a = self.db.email_assets.find_one({"_id": d["hash"]}, {"bytes": 1, "content_type": 1})
            out.append({"name": d["_id"], "hash": d["hash"],
                        "bytes": (a or {}).get("bytes", 0),
                        "type": (a or {}).get("content_type", "")})
        return out

    def get_asset(self, h: str) -> dict | None:
        return self.db.email_assets.find_one({"_id": h})

    def library_topics(self) -> list[str]:
        return sorted(t for t in self.db.leads.distinct("topics") if t)

    def library_campaigns(self) -> list[dict]:
        """Every campaign an audience can name, with its reachable count.

        Counted by distinct email, because a blast cares about people, not lead rows
        — the same person can sit in two campaigns.

        Reads BOTH collections on purpose. Deriving this from leads alone made the
        marketing chips disagree with the Sales campaign picker in both directions:
        a defined campaign with no leads (knowella-safety-ai) vanished from
        marketing, and leads whose campaign had been deleted (zz-par-test) showed up
        as a campaign that exists nowhere else in the app. Both are reported and
        labelled, because "these two lists don't match" deserves a visible answer
        rather than a filter that quietly drops one side.
        """
        seen: dict[str, set] = {}
        for d in self.db.leads.find({}, {"campaign": 1, "lead.email": 1}):
            email = ((d.get("lead") or {}).get("email") or "").strip().lower()
            if email and d.get("campaign"):
                seen.setdefault(d["campaign"], set()).add(email)
        defined = set(self.campaign_names())
        out = [{"name": n, "count": len(seen.get(n, ())), "orphan": False} for n in defined]
        out += [{"name": n, "count": len(v), "orphan": True}
                for n, v in seen.items() if n not in defined]
        # orphans last: they are a thing to clean up, not a thing to send to
        return sorted(out, key=lambda c: (c["orphan"], -c["count"], c["name"]))

    # saved audiences: named, reusable filters — resolved live at every use
    def create_audience(self, name: str, flt: dict) -> str:
        import uuid
        aid = uuid.uuid4().hex[:10]
        self.db.audiences.insert_one({"_id": aid, "name": name, "filter": flt,
                                      "created_at": datetime.now(timezone.utc).isoformat()})
        return aid

    def list_audiences(self) -> list[dict]:
        return list(self.db.audiences.find({}).sort("created_at", -1))

    def delete_audience(self, aid: str) -> None:
        self.db.audiences.delete_one({"_id": aid})

    def engagement_by_email(self) -> dict:
        """{email: {'opened': bool, 'clicked': bool}} from every blast's webhook events —
        the marketing engine's intent signal, consumed by audiences and the Library."""
        out: dict[str, dict] = {}
        for d in self.db.blast_recipients.find({}, {"email": 1, "events": 1}):
            ev = set(d.get("events") or [])
            e = out.setdefault(d["email"], {"opened": False, "clicked": False})
            e["opened"] = e["opened"] or bool({"opened", "clicked"} & ev)
            e["clicked"] = e["clicked"] or "clicked" in ev
        return out

    def create_blast(self, doc: dict) -> str:
        import uuid
        bid = uuid.uuid4().hex[:12]
        doc = {**doc, "_id": bid, "status": "draft",
               "created_at": datetime.now(timezone.utc).isoformat(),
               "stats": {k: 0 for k in ("recipients", "accepted", "failed", "delivered",
                                        "opened", "clicked", "bounced", "spam", "unsubs")},
               "progress": {"done": 0, "total": 0}}
        self.db.blasts.insert_one(doc)
        return bid

    def get_blast(self, bid: str) -> dict | None:
        return self.db.blasts.find_one({"_id": bid})

    def list_blasts(self) -> list[dict]:
        return list(self.db.blasts.find({}).sort("created_at", -1))

    def update_blast(self, bid: str, fields: dict) -> None:
        self.db.blasts.update_one({"_id": bid}, {"$set": fields})

    def delete_blast(self, bid: str) -> None:
        self.db.blasts.delete_one({"_id": bid})
        self.db.blast_recipients.delete_many({"blast": bid})

    def add_blast_recipient(self, bid: str, email: str, key: str, message_id: str, ok: bool) -> None:
        self.db.blast_recipients.replace_one(
            {"_id": f"{bid}::{email}"},
            {"_id": f"{bid}::{email}", "blast": bid, "email": email, "lead_key": key,
             "message_id": message_id, "accepted": ok, "events": []}, upsert=True)

    # --- publications: the marketing analogue of a campaign ---------------------
    # Sales has a campaign holding the ICP, offer, voice and the knowledge block that
    # bounds what may be stated as fact. Marketing had nothing above a blast, so every
    # send was a standalone with no product, no voice and nothing for a writer — human
    # or model — to be grounded by. A publication is that container: recipients
    # subscribe to it, issues belong to it, and its knowledge block is the only thing
    # a generated draft may treat as true.
    def create_publication(self, doc: dict) -> str:
        pid = uuid.uuid4().hex[:10]
        self.db.publications.insert_one({
            "_id": pid, "name": doc.get("name", ""), "product": doc.get("product", ""),
            "description": doc.get("description", ""), "knowledge": doc.get("knowledge", ""),
            "voice": doc.get("voice", ""), "audience": doc.get("audience") or {},
            "from_address": doc.get("from_address", ""), "reply_to": doc.get("reply_to", ""),
            "issues": 0, "created_at": datetime.now(timezone.utc).isoformat()})
        return pid

    def list_publications(self) -> list[dict]:
        return list(self.db.publications.find({}).sort("created_at", 1))

    def get_publication(self, pid: str) -> dict | None:
        return self.db.publications.find_one({"_id": pid}) if pid else None

    def update_publication(self, pid: str, patch: dict) -> None:
        allowed = {"name", "product", "description", "knowledge", "voice",
                   "audience", "from_address", "reply_to"}
        clean = {k: v for k, v in patch.items() if k in allowed}
        if clean:
            self.db.publications.update_one({"_id": pid}, {"$set": clean})

    def delete_publication(self, pid: str) -> None:
        """Issues already sent keep their publication_id — deleting the publication
        must not rewrite history, only stop new issues being filed under it."""
        self.db.publications.delete_one({"_id": pid})

    def next_issue_no(self, pid: str) -> int:
        """Claim the next issue number. Atomic, so two sends can't both be #4."""
        d = self.db.publications.find_one_and_update(
            {"_id": pid}, {"$inc": {"issues": 1}}, return_document=True)
        return int((d or {}).get("issues") or 1)

    # --- subscribers: consent as a stored fact, not an assumption ---------------
    # A lead's address means we found them. A subscriber's means they asked. Those
    # are different things and a newsletter may only go to the second, so it lives
    # in its own collection rather than as a flag on a lead that was never asked.
    def add_subscriber(self, email: str, name: str = "", source: str = "") -> dict:
        """Record a pending subscription. Idempotent: re-subscribing someone already
        confirmed leaves them confirmed rather than knocking them back to pending."""
        e = (email or "").strip().lower()
        now = datetime.now(timezone.utc).isoformat()
        existing = self.db.subscribers.find_one({"_id": e})
        if existing and existing.get("status") == "confirmed":
            return existing
        doc = {"_id": e, "name": name.strip(), "source": source or "web",
               "status": "pending", "created_at": (existing or {}).get("created_at", now),
               "asked_at": now,
               # What they asked for. Empty = everything, which is what somebody who
               # subscribed without ticking anything has actually said.
               "topics": (existing or {}).get("topics") or []}
        self.db.subscribers.replace_one({"_id": e}, doc, upsert=True)
        return doc

    def subscriber_prefs(self, email: str) -> list[str]:
        d = self.db.subscribers.find_one({"_id": (email or "").strip().lower()}) or {}
        return d.get("topics") or []

    def set_subscriber_prefs(self, email: str, topics: list[str]) -> bool:
        """What this person wants to hear about. Returns False for an address that
        isn't a subscriber, so a tampered token changes nothing."""
        e = (email or "").strip().lower()
        r = self.db.subscribers.update_one({"_id": e}, {"$set": {"topics": list(topics)}})
        return r.matched_count > 0

    def confirm_subscriber(self, email: str) -> bool:
        """Double opt-in landing. True only if there was something to confirm."""
        e = (email or "").strip().lower()
        r = self.db.subscribers.update_one(
            {"_id": e}, {"$set": {"status": "confirmed",
                                  "confirmed_at": datetime.now(timezone.utc).isoformat()}})
        return r.matched_count > 0

    def drop_subscriber(self, email: str) -> None:
        """Unsubscribing has to end the subscription too, not just add a suppression
        row — otherwise the audience keeps counting someone who opted out."""
        self.db.subscribers.update_one(
            {"_id": (email or "").strip().lower()},
            {"$set": {"status": "unsubscribed",
                      "unsubscribed_at": datetime.now(timezone.utc).isoformat()}})

    def list_subscribers(self, status: str = "") -> list[dict]:
        q = {"status": status} if status else {}
        return list(self.db.subscribers.find(q).sort("created_at", -1))

    def subscriber_counts(self) -> dict:
        out = {"pending": 0, "confirmed": 0, "unsubscribed": 0}
        for d in self.db.subscribers.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
            if d["_id"] in out:
                out[d["_id"]] = d["n"]
        return out

    def blast_sent_emails(self, bid: str) -> set:
        """Who this blast has already gone to. Sending in batches is only safe if a
        second run can tell which addresses are already done — otherwise 'send the
        rest' silently mails the first batch a second time."""
        return {d["email"] for d in
                self.db.blast_recipients.find({"blast": bid}, {"email": 1})}

    def mark_blast_event(self, bid: str, email: str, event: str) -> bool:
        """Record a webhook event once per recipient; True only the FIRST time (so
        stats count unique people, not repeat opens)."""
        r = self.db.blast_recipients.update_one(
            {"_id": f"{bid}::{email}", "events": {"$ne": event}},
            {"$addToSet": {"events": event}})
        return r.modified_count > 0

    def inc_blast_stat(self, bid: str, field: str, n: int = 1) -> None:
        self.db.blasts.update_one({"_id": bid}, {"$inc": {f"stats.{field}": n}})

    # --- sources: WHERE a lead came from, and what that place produced ---------
    # The attribution spine. Without it the engage->capture->nurture loop is just
    # activity; with it we can see which LinkedIn group / publication / community
    # actually yields meetings, and spend the next hour there.
    def upsert_source(self, name: str, stype: str = "linkedin_post", url: str = "") -> str:
        """Find-or-create by (name, type). Returns the source id."""
        key = (name or "").strip() or "unattributed"
        d = self.db.sources.find_one({"name": key, "type": stype})
        if d:
            if url and not d.get("url"):
                self.db.sources.update_one({"_id": d["_id"]}, {"$set": {"url": url}})
            return d["_id"]
        sid = uuid.uuid4().hex[:10]
        self.db.sources.insert_one({"_id": sid, "name": key, "type": stype, "url": url,
                                    "created_at": datetime.now(timezone.utc).isoformat()})
        return sid

    def list_sources(self) -> list[dict]:
        return list(self.db.sources.find({}).sort("created_at", -1))

    def delete_source(self, sid: str) -> None:
        self.db.sources.delete_one({"_id": sid})
        self.db.leads.update_many({"source_id": sid}, {"$unset": {"source_id": ""}})

    def set_source_notes(self, sid: str, notes: str) -> None:
        """Questions people actually asked in that place — the content backlog."""
        self.db.sources.update_one({"_id": sid}, {"$set": {"notes": notes}})

    def source_funnel(self) -> dict:
        """{source_id: {leads, with_email, sent, replied, meetings, opened, clicked}} —
        one pass over the leads, then set-membership against the other collections."""
        by_source: dict = {}
        keys_of: dict = {}
        for d in self.db.leads.find({"source_id": {"$exists": True}},
                                    {"source_id": 1, "status": 1, "lead.email": 1}):
            sid = d.get("source_id")
            if not sid:
                continue
            f = by_source.setdefault(sid, {"leads": 0, "with_email": 0, "sent": 0,
                                           "replied": 0, "meetings": 0, "engaged": 0})
            f["leads"] += 1
            if ((d.get("lead") or {}).get("email") or ""):
                f["with_email"] += 1
            keys_of.setdefault(sid, []).append(d["_id"])
        all_keys = [k for ks in keys_of.values() for k in ks]
        if not all_keys:
            return by_source
        sent = {d["_id"] for d in self.db.sends.find({"_id": {"$in": all_keys}}, {"_id": 1})}
        replied = {d["_id"] for d in self.db.replies.find({"_id": {"$in": all_keys}}, {"_id": 1})}
        met = {d["_id"] for d in self.db.meetings.find({"_id": {"$in": all_keys}}, {"_id": 1})}
        engaged = self.engagement_by_email()          # marketing opens/clicks, keyed by email
        email_of = {d["_id"]: ((d.get("lead") or {}).get("email") or "").lower()
                    for d in self.db.leads.find({"_id": {"$in": all_keys}}, {"lead.email": 1})}
        for sid, ks in keys_of.items():
            f = by_source[sid]
            for k in ks:
                if k in sent:
                    f["sent"] += 1
                if k in replied:
                    f["replied"] += 1
                if k in met:
                    f["meetings"] += 1
                e = engaged.get(email_of.get(k, ""))
                if e and (e.get("opened") or e.get("clicked")):
                    f["engaged"] += 1
        return by_source

    def backfill_source_ids(self) -> int:
        """One-time: give the leads that pre-date attribution the source they came
        from, recovered from the `lead.source` they were saved with. Without this the
        Sources page opens empty and every new LinkedIn group is compared against
        nothing — the Apollo baseline is the whole point of the comparison.
        Idempotent: only ever touches leads that have no source_id."""
        by_value: dict[str, list] = {}
        for d in self.db.leads.find({"source_id": {"$exists": False}},
                                    {"lead.source": 1}):
            v = ((d.get("lead") or {}).get("source") or "").strip()
            if v:
                by_value.setdefault(v, []).append(d["_id"])
        n = 0
        for v, keys in by_value.items():
            if v.lower() == "apollo":
                sid = self.upsert_source("Apollo search", "apollo")
            else:
                sid = self.upsert_source(f"CSV import ({v})", "import")
            for i in range(0, len(keys), 1000):     # chunked: 4k+ leads in one go
                self.db.leads.update_many({"_id": {"$in": keys[i:i + 1000]}},
                                          {"$set": {"source_id": sid}})
            n += len(keys)
        return n

    # --- signals: the monitoring inbox -----------------------------------------
    # Platforms push to us (notification email, RSS); this is where those land as
    # one queue instead of five inboxes. See src/signals.py for the parsers.
    def add_signal(self, doc: dict) -> bool:
        """Upsert on the dedupe key. True only when the signal is genuinely new, so
        re-polling a feed or being sent the same notification twice is a no-op."""
        key = doc.get("dedupe") or ""
        if key and self.db.signals.find_one({"dedupe": key}, {"_id": 1}):
            return False
        doc = dict(doc)
        doc["_id"] = uuid.uuid4().hex[:12]
        doc.setdefault("status", "new")
        doc.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        self.db.signals.insert_one(doc)
        return True

    def list_signals(self, status: str = "", limit: int = 300) -> list[dict]:
        q = {"status": status} if status else {}
        return list(self.db.signals.find(q).sort("created_at", -1).limit(limit))

    def signal_counts(self) -> dict:
        out = {"new": 0, "engaged": 0, "ignored": 0}
        for d in self.db.signals.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
            out[d["_id"] or "new"] = d["n"]
        return out

    def set_signal_status(self, sid: str, status: str) -> None:
        self.db.signals.update_one({"_id": sid}, {"$set": {
            "status": status, "acted_at": datetime.now(timezone.utc).isoformat()}})

    def delete_signal(self, sid: str) -> None:
        self.db.signals.delete_one({"_id": sid})

    def clear_signals(self, scope: str = "") -> int:
        """Dismiss open signals. Marks them ignored rather than deleting, so the
        dedupe keys survive and a cleared item doesn't return on the next poll.

        scope='mentions' clears only the third register — the signals with nobody to
        contact. Filtering by channel would be wrong: a LinkedIn comment and a Google
        Alert hit both arrive by email, and only one of them is a person.
        """
        q: dict = {"status": "new"}
        if scope == "mentions":
            q["kind"] = {"$ne": "citation"}
            q["channel"] = {"$ne": "manual"}
            q["$or"] = [{"person": ""}, {"person": {"$exists": False}}]
        return self.db.signals.update_many(q, {"$set": {
            "status": "ignored",
            "acted_at": datetime.now(timezone.utc).isoformat()}}).modified_count


    # --- backlog: the questions buyers asked, which is what to write next ------
    def add_backlog(self, question: str, source_id: str = "", signal_id: str = "",
                    url: str = "") -> str:
        bid = uuid.uuid4().hex[:10]
        self.db.backlog.insert_one({"_id": bid, "question": question, "source_id": source_id,
                                    "signal_id": signal_id, "url": url, "status": "idea",
                                    "created_at": datetime.now(timezone.utc).isoformat()})
        return bid

    def list_backlog(self) -> list[dict]:
        return list(self.db.backlog.find({}).sort("created_at", -1))

    def set_backlog_status(self, bid: str, status: str) -> None:
        self.db.backlog.update_one({"_id": bid}, {"$set": {"status": status}})

    def delete_backlog(self, bid: str) -> None:
        self.db.backlog.delete_one({"_id": bid})

    # --- capture tokens: one per person, revocable independently ---------------
    # A single shared token meant generating one for a teammate silently broke
    # everyone else's extension. Each token is stored only as its SHA-256.
    def create_capture_token(self, label: str, token_hash: str,
                             owner: str = "", owner_email: str = "") -> str:
        import uuid
        tid = uuid.uuid4().hex[:10]
        self.db.capture_tokens.insert_one({
            "_id": tid, "label": label, "hash": token_hash,
            # the person it acts as: captures land only in campaigns they may see
            "owner": owner, "owner_email": owner_email,
            "created_at": datetime.now(timezone.utc).isoformat()})
        return tid

    def get_capture_token(self, tid: str) -> dict | None:
        return self.db.capture_tokens.find_one({"_id": tid})

    def list_capture_tokens(self) -> list[dict]:
        return list(self.db.capture_tokens.find({}).sort("created_at", -1))

    def revoke_capture_token(self, tid: str) -> None:
        self.db.capture_tokens.delete_one({"_id": tid})

    def find_capture_token(self, token_hash: str) -> dict | None:
        """Match a presented token and stamp its last use (so a stale token is
        identifiable before revoking it)."""
        d = self.db.capture_tokens.find_one({"hash": token_hash})
        if d:
            self.db.capture_tokens.update_one(
                {"_id": d["_id"]},
                {"$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}})
        return d

    # --- app settings (single-value, e.g. the LinkedIn-capture token hash) ---
    def set_setting(self, key: str, value: str) -> None:
        self.db.settings.replace_one({"_id": key}, {"_id": key, "value": value}, upsert=True)

    def get_setting(self, key: str) -> str | None:
        d = self.db.settings.find_one({"_id": key})
        return d["value"] if d else None

    def delete_setting(self, key: str) -> None:
        self.db.settings.delete_one({"_id": key})

    # --- suppression (do-not-contact) ----------------------------------------
    # Global compliance list: emails and whole domains that must never be
    # contacted again. Enforced at pull, pipeline, and send.
    @staticmethod
    def _suppress_keys(value: str) -> str:
        return (value or "").strip().lower().lstrip("@")

    def suppress(self, value: str, reason: str = "") -> None:
        """Add an email or a domain (e.g. 'acme.com') to the do-not-contact list."""
        v = self._suppress_keys(value)
        if v:
            self.db.suppression.replace_one(
                {"_id": v}, {"_id": v, "reason": reason,
                             "added_at": datetime.now(timezone.utc).isoformat()}, upsert=True)

    def unsuppress(self, value: str) -> None:
        self.db.suppression.delete_one({"_id": self._suppress_keys(value)})

    def is_suppressed(self, email: str) -> bool:
        """True if the exact email OR its domain is on the do-not-contact list."""
        e = self._suppress_keys(email)
        if not e:
            return False
        keys = [e]
        if "@" in e:
            keys.append(e.rsplit("@", 1)[-1])
        return self.db.suppression.count_documents({"_id": {"$in": keys}}) > 0

    @staticmethod
    def _is_sup(email: str, sup: set[str]) -> bool:
        e = (email or "").strip().lower().lstrip("@")
        return bool(e) and (e in sup or ("@" in e and e.rsplit("@", 1)[-1] in sup))

    def suppressed_set(self) -> set[str]:
        """The whole do-not-contact list, for checking many addresses at once.

        is_suppressed costs one round trip per address, which is right for one
        address and ruinous for a list: resolving the 4,735-person Library made 4,735
        calls to Atlas against a collection of 156 documents, and the audience
        preview took minutes. Fetch it once instead."""
        return {d["_id"] for d in self.db.suppression.find({}, {"_id": 1})}

    def list_suppressed(self) -> list[dict]:
        return [{"value": d["_id"], "reason": d.get("reason", ""), "added_at": d.get("added_at", "")}
                for d in self.db.suppression.find().sort("added_at", -1)]

    # --- reply classification (per message, cached) ---------------------------
    def get_reply_classes(self, msg_ids: list[str]) -> dict:
        """message id -> label, for messages already classified."""
        if not msg_ids:
            return {}
        return {d["_id"]: d["label"] for d in self.db.reply_class.find({"_id": {"$in": msg_ids}})}

    def save_reply_class(self, msg_id: str, email: str, label: str) -> None:
        self.db.reply_class.replace_one(
            {"_id": msg_id},
            {"_id": msg_id, "email": (email or "").lower(), "label": label,
             "at": datetime.now(timezone.utc).isoformat()}, upsert=True)

    # --- A/B outcomes: reply attribution + per-variant stats -----------------
    def mark_replied(self, key: str, label: str = "") -> None:
        # `at`: when we first saw the reply (Apollo gives no reply time). Older rows have none.
        self.db.replies.update_one(
            {"_id": key},
            {"$setOnInsert": {"replied": True, "at": datetime.now(timezone.utc).isoformat()},
             **({"$set": {"label": label}} if label else {})},
            upsert=True)

    # --- outcomes: the metrics that matter (positive replies, meetings) -------
    def mark_meeting(self, key: str) -> None:
        self.db.meetings.replace_one(
            {"_id": key}, {"_id": key, "at": datetime.now(timezone.utc).isoformat()}, upsert=True)

    def unmark_meeting(self, key: str) -> None:
        self.db.meetings.delete_one({"_id": key})

    def meeting_keys(self, keys: list[str]) -> set:
        return {d["_id"] for d in self.db.meetings.find({"_id": {"$in": keys}}, {"_id": 1})}

    def outcome_stats(self, campaign: str) -> dict:
        """Sent / replies by classification / positive-reply rate / meetings booked.

        'positive' = replies classified interested. OOO auto-replies never reach the
        replies collection, so they don't pollute these numbers.
        """
        keys = [d["_id"] for d in self.db.leads.find({"campaign": campaign}, {"_id": 1})]
        if not keys:
            return {"sent": 0, "replies": 0, "by_label": {}, "positive": 0,
                    "positive_rate": 0.0, "meetings": 0}
        sent = self.db.sends.count_documents({"_id": {"$in": keys}})
        by_label: dict = {}
        replies = 0
        for d in self.db.replies.find({"_id": {"$in": keys}}):
            replies += 1
            label = d.get("label") or "other"
            by_label[label] = by_label.get(label, 0) + 1
        positive = by_label.get("interested", 0)
        return {
            "sent": sent, "replies": replies, "by_label": by_label,
            "positive": positive,
            "positive_rate": round(positive / sent * 100, 1) if sent else 0.0,
            "meetings": len(self.meeting_keys(keys)),
        }

    def ab_stats(self, campaign: str) -> dict:
        keys = [d["_id"] for d in self.db.leads.find({"campaign": campaign}, {"_id": 1})]
        if not keys:
            return {}
        sent = {d["_id"] for d in self.db.sends.find({"_id": {"$in": keys}}, {"_id": 1})}
        replied = {}
        for d in self.db.replies.find({"_id": {"$in": keys}}):
            replied[d["_id"]] = d.get("label") or "other"
        out: dict = {}
        for d in self.db.outbox.find({"_id": {"$in": keys}}, {"_id": 1, "variant": 1}):
            v = d.get("variant", "signal")
            s = out.setdefault(v, {"drafted": 0, "sent": 0, "replied": 0, "interested": 0})
            s["drafted"] += 1
            if d["_id"] in sent:
                s["sent"] += 1
            if d["_id"] in replied:
                s["replied"] += 1
                if replied[d["_id"]] == "interested":
                    s["interested"] += 1
        return out

    # --- reviews -------------------------------------------------------------
    def set_review(self, key: str, decision: str) -> None:
        self.db.reviews.update_one({"_id": key}, {"$set": {"decision": decision}}, upsert=True)

    def get_review(self, key: str) -> str | None:
        d = self.db.reviews.find_one({"_id": key})
        return d["decision"] if d else None

    # --- email verification (cached by email) -------------------------------
    def get_verify(self, email: str) -> str | None:
        d = self.db.verify.find_one({"_id": email})
        return d["status"] if d else None

    def save_verify(self, email: str, status: str) -> None:
        self.db.verify.replace_one({"_id": email}, {"_id": email, "status": status}, upsert=True)
