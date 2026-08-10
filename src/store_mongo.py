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

from pymongo import MongoClient

from .models import Draft, GateResult, Lead, Research


class MongoStore:
    def __init__(self, uri: str, db_name: str = "outreach"):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        try:
            self.client.admin.command("ping")
        except Exception as e:
            raise RuntimeError(f"Could not connect to MongoDB: {e}") from e
        self.db = self.client[db_name]

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
        self.db.campaigns.replace_one({"_id": slug}, {"_id": slug, "cfg": cfg}, upsert=True)

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
                    source_id: str = "") -> None:
        # _id is campaign-scoped so the SAME person can live in multiple campaigns as
        # independent rows (own research/draft/status). Re-importing into the SAME
        # campaign still dedups (same _id, $setOnInsert no-ops).
        sid = self._scoped(campaign, self._base_key(lead))
        doc = {"campaign": campaign, "status": "new", "lead": lead.model_dump(),
               "topics": topics or [], "pulled_at": datetime.now(timezone.utc)}
        if source_id:      # which LinkedIn group / publication / community produced them
            doc["source_id"] = source_id
        self.db.leads.update_one({"_id": sid}, {"$setOnInsert": doc}, upsert=True)

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

    def leads(self, campaign: str, status: str | None = None) -> list[Lead]:
        q = {"campaign": campaign}
        if status:
            q["status"] = status
        out = []
        for d in self.db.leads.find(q):
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
                "lead.email": 1, "lead.source": 1, "lead.raw.id": 1}
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
                        "apollo_id": (L.get("raw") or {}).get("id") or ""})
        return out

    def save_lead_error(self, key: str, reason: str) -> None:
        """Persist WHY a lead errored, so mass failures are diagnosable after the fact."""
        self.db.leads.update_one({"_id": key}, {"$set": {"error": reason}})

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
    def audience_leads(self, flt: dict) -> list[dict]:
        """Resolve an audience filter against the WHOLE Library, deduped by email.

        flt: {topics: [..] any-match, statuses: [..], exclude_sent: bool,
        engagement: ''|'opened'|'clicked'}. Emailless and suppressed people never make
        it in. exclude_sent drops anyone the sales engine has already emailed in ANY
        campaign (the 'never pitched' audience); engagement narrows to people who
        opened/clicked a previous blast — the warm slice.
        Returns [{email, key, lead}] — lead is the full Lead for merge rendering."""
        # subscribers_only is a different question from every other filter: not
        # "who in the Library matches" but "who actually asked for this". It is the
        # only audience a newsletter may legally and safely go to, so it short-
        # circuits the Library entirely rather than narrowing it.
        if flt.get("subscribers_only"):
            out: dict[str, dict] = {}
            for d in self.list_subscribers("confirmed"):
                email = d["_id"]
                if self.is_suppressed(email):
                    continue
                lead = self.lead_by_email(email) or Lead(
                    first_name=(d.get("name") or "").split(" ")[0], email=email)
                out[email] = {"email": email, "key": f"sub::{email}", "lead": lead}
            return list(out.values())

        topics = set(flt.get("topics") or [])
        statuses = set(flt.get("statuses") or [])
        want_eng = flt.get("engagement") or ""
        engaged = self.engagement_by_email() if want_eng else {}
        rows = list(self.db.leads.find({}))
        sent_emails = {(Lead.model_validate(d["lead"]).email or "").lower()
                       for d in rows if d.get("status") == "sent"} if flt.get("exclude_sent") else set()
        out: dict[str, dict] = {}
        for d in rows:
            lead = Lead.model_validate(d["lead"])
            email = (lead.email or "").strip().lower()
            if not email or email in out or email in sent_emails:
                continue
            if topics and not (topics & set(d.get("topics") or [])):
                continue
            if statuses and d.get("status") not in statuses:
                continue
            if want_eng and not engaged.get(email, {}).get(want_eng):
                continue
            if self.is_suppressed(email):
                continue
            out[email] = {"email": email, "key": d["_id"], "lead": lead}
        return list(out.values())

    def lead_by_email(self, email: str) -> Lead | None:
        """A subscriber who is also in the Library gets their real merge fields —
        first name, company, title — instead of an empty shell."""
        d = self.db.leads.find_one({"lead.email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        return Lead.model_validate(d["lead"]) if d else None

    def library_topics(self) -> list[str]:
        return sorted(t for t in self.db.leads.distinct("topics") if t)

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
               "asked_at": now}
        self.db.subscribers.replace_one({"_id": e}, doc, upsert=True)
        return doc

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
    def create_capture_token(self, label: str, token_hash: str) -> str:
        import uuid
        tid = uuid.uuid4().hex[:10]
        self.db.capture_tokens.insert_one({
            "_id": tid, "label": label, "hash": token_hash,
            "created_at": datetime.now(timezone.utc).isoformat()})
        return tid

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
        self.db.replies.update_one(
            {"_id": key},
            {"$setOnInsert": {"replied": True}, **({"$set": {"label": label}} if label else {})},
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
