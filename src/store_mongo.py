"""MongoDB-backed store — same interface as the SQLite Store, drop-in replacement.

Selected automatically when MONGO_URI is set (see main.open_store). Keeps outreach
data in its OWN database (default 'outreach'), isolated from any product DB.

Lead `key` is used as the Mongo _id everywhere, so upserts are natural and a lead
can never be duplicated. Stage caches (research/draft/gate) match on (key, input_hash)
exactly like SQLite, so the incremental-build behavior is identical.
"""
from __future__ import annotations

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

    # --- leads ---------------------------------------------------------------
    def upsert_lead(self, lead: Lead, campaign: str, topics: list | None = None) -> None:
        self.db.leads.update_one(
            {"_id": lead.key},
            {"$setOnInsert": {"campaign": campaign, "status": "new", "lead": lead.model_dump(),
                              "topics": topics or []}},
            upsert=True,
        )

    def all_leads(self, status: str | None = None) -> list[dict]:
        """Lead summaries across all campaigns, optionally filtered by status.

        The library passes status='excluded' — the bench of leads removed from
        campaigns (never deleted, only flipped to 'excluded' with drafts cleared),
        kept for reuse. Returns raw rows; the API adds function bucket + topics.
        """
        q = {"status": status} if status else {}
        out = []
        for d in self.db.leads.find(q):
            lead = Lead.model_validate(d["lead"])
            out.append({"key": d["_id"], "campaign": d.get("campaign", ""),
                        "status": d.get("status", ""), "topics": d.get("topics") or [],
                        "name": lead.full_name, "title": lead.title, "company": lead.company,
                        "email": lead.email, "source": lead.source})
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
        self.db.leads.update_one({"_id": key}, {"$set": {"status": status}})

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
        out = []
        for d in self.db.leads.find({"campaign": campaign}):
            lead = Lead.model_validate(d["lead"])
            out.append({"key": d["_id"], "status": d["status"], "name": lead.full_name,
                        "company": lead.company, "title": lead.title, "email": lead.email,
                        "source": lead.source,
                        # Apollo person id — lets the UI offer "find more like this" (lookalike seed)
                        "apollo_id": (lead.raw or {}).get("id") or ""})
        return out

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
