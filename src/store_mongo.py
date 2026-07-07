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
    def upsert_lead(self, lead: Lead, campaign: str) -> None:
        self.db.leads.update_one(
            {"_id": lead.key},
            {"$setOnInsert": {"campaign": campaign, "status": "new", "lead": lead.model_dump()}},
            upsert=True,
        )

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
                        "source": lead.source})
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
        return {"subject": d["subject"], "body": d["body"], "angle": d.get("angle", ""),
                "verdict": d["verdict"], "edited": bool(d.get("edited", False)),
                "variant": d.get("variant", "signal")}

    def update_outbox(self, key: str, subject: str, body: str) -> None:
        self.db.outbox.update_one({"_id": key}, {"$set": {"subject": subject, "body": body, "edited": True}})

    # --- A/B outcomes: reply attribution + per-variant stats -----------------
    def mark_replied(self, key: str) -> None:
        self.db.replies.update_one({"_id": key}, {"$setOnInsert": {"replied": True}}, upsert=True)

    def ab_stats(self, campaign: str) -> dict:
        keys = [d["_id"] for d in self.db.leads.find({"campaign": campaign}, {"_id": 1})]
        if not keys:
            return {}
        sent = {d["_id"] for d in self.db.sends.find({"_id": {"$in": keys}}, {"_id": 1})}
        replied = {d["_id"] for d in self.db.replies.find({"_id": {"$in": keys}}, {"_id": 1})}
        out: dict = {}
        for d in self.db.outbox.find({"_id": {"$in": keys}}, {"_id": 1, "variant": 1}):
            v = d.get("variant", "signal")
            s = out.setdefault(v, {"drafted": 0, "sent": 0, "replied": 0})
            s["drafted"] += 1
            if d["_id"] in sent:
                s["sent"] += 1
            if d["_id"] in replied:
                s["replied"] += 1
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
