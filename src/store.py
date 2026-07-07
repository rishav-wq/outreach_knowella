"""SQLite state store — the backbone. Persisted, resumable, idempotent.

Each lead is a row with a status; each stage's output is cached and keyed by an
`input_hash`, so re-running a stage with unchanged inputs is a no-op (incremental
build). Crash-resume and cheap prompt iteration both fall out of this for free.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from .models import Draft, GateResult, Lead, Research

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  key        TEXT PRIMARY KEY,
  campaign   TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'new',
  lead_json  TEXT NOT NULL,
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS research (
  key TEXT PRIMARY KEY, input_hash TEXT NOT NULL, data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
  key TEXT PRIMARY KEY, input_hash TEXT NOT NULL, data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gate (
  key TEXT PRIMARY KEY, input_hash TEXT NOT NULL, verdict TEXT NOT NULL,
  reason TEXT, data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sends (
  key TEXT PRIMARY KEY, platform TEXT, platform_id TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, stage TEXT, model TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS outbox (
  key TEXT PRIMARY KEY, subject TEXT, body TEXT, angle TEXT, verdict TEXT,
  edited INTEGER DEFAULT 0, variant TEXT DEFAULT 'signal',
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS reviews (
  key TEXT PRIMARY KEY, decision TEXT, updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS verify (
  email TEXT PRIMARY KEY, status TEXT, updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS replies (
  key TEXT PRIMARY KEY, replied_at TEXT DEFAULT (datetime('now'))
);
"""


def hash_inputs(*parts) -> str:
    """Stable short hash of arbitrary JSON-able inputs (cache-invalidation key)."""
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        for mig in ("ALTER TABLE outbox ADD COLUMN edited INTEGER DEFAULT 0",
                    "ALTER TABLE outbox ADD COLUMN variant TEXT DEFAULT 'signal'"):
            try:
                self.conn.execute(mig)   # migrate older dbs missing newer columns
            except Exception:
                pass
        self.conn.commit()

    # --- leads ---------------------------------------------------------------
    def upsert_lead(self, lead: Lead, campaign: str) -> None:
        self.conn.execute(
            "INSERT INTO leads(key,campaign,status,lead_json) VALUES(?,?,'new',?) "
            "ON CONFLICT(key) DO NOTHING",
            (lead.key, campaign, lead.model_dump_json()),
        )
        self.conn.commit()

    def set_status(self, key: str, status: str) -> None:
        self.conn.execute(
            "UPDATE leads SET status=?, updated_at=datetime('now') WHERE key=?",
            (status, key),
        )
        self.conn.commit()

    def update_lead(self, lead: Lead) -> None:
        self.conn.execute("UPDATE leads SET lead_json=? WHERE key=?", (lead.model_dump_json(), lead.key))
        self.conn.commit()

    def get_lead(self, key: str) -> Lead | None:
        r = self.conn.execute("SELECT lead_json FROM leads WHERE key=?", (key,)).fetchone()
        if not r:
            return None
        lead = Lead.model_validate_json(r["lead_json"])
        lead.stored_key = key
        return lead

    def leads(self, campaign: str, status: str | None = None) -> list[Lead]:
        q, args = "SELECT key, lead_json FROM leads WHERE campaign=?", [campaign]
        if status:
            q += " AND status=?"
            args.append(status)
        rows = self.conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            lead = Lead.model_validate_json(r["lead_json"])
            lead.stored_key = r["key"]
            out.append(lead)
        return out

    def counts(self, campaign: str) -> dict:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) c FROM leads WHERE campaign=? GROUP BY status",
            (campaign,),
        ).fetchall()
        return {r["status"]: r["c"] for r in rows}

    def lead_summaries(self, campaign: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT key, status, lead_json FROM leads WHERE campaign=?", (campaign,)
        ).fetchall()
        out = []
        for r in rows:
            lead = Lead.model_validate_json(r["lead_json"])
            out.append({"key": r["key"], "status": r["status"], "name": lead.full_name,
                        "company": lead.company, "title": lead.title, "email": lead.email,
                        "source": lead.source})
        return out

    # --- research (cached by input_hash) ------------------------------------
    def get_research(self, key: str, input_hash: str) -> Research | None:
        r = self.conn.execute(
            "SELECT data_json FROM research WHERE key=? AND input_hash=?", (key, input_hash)
        ).fetchone()
        return Research.model_validate_json(r["data_json"]) if r else None

    def get_research_any(self, key: str) -> Research | None:
        """Latest stored research for a lead, ignoring input_hash — for display."""
        r = self.conn.execute("SELECT data_json FROM research WHERE key=?", (key,)).fetchone()
        return Research.model_validate_json(r["data_json"]) if r else None

    def save_research(self, key: str, input_hash: str, research: Research) -> None:
        self.conn.execute(
            "INSERT INTO research(key,input_hash,data_json) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET input_hash=excluded.input_hash, data_json=excluded.data_json",
            (key, input_hash, research.model_dump_json()),
        )
        self.conn.commit()

    # --- drafts (cached by input_hash) --------------------------------------
    def get_draft(self, key: str, input_hash: str) -> Draft | None:
        r = self.conn.execute(
            "SELECT data_json FROM drafts WHERE key=? AND input_hash=?", (key, input_hash)
        ).fetchone()
        return Draft.model_validate_json(r["data_json"]) if r else None

    def save_draft(self, key: str, input_hash: str, draft: Draft) -> None:
        self.conn.execute(
            "INSERT INTO drafts(key,input_hash,data_json) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET input_hash=excluded.input_hash, data_json=excluded.data_json",
            (key, input_hash, draft.model_dump_json()),
        )
        self.conn.commit()

    # --- gate (cached by the draft's input_hash) ----------------------------
    def get_gate(self, key: str, input_hash: str) -> GateResult | None:
        r = self.conn.execute(
            "SELECT data_json FROM gate WHERE key=? AND input_hash=?", (key, input_hash)
        ).fetchone()
        return GateResult.model_validate_json(r["data_json"]) if r else None

    def save_gate(self, key: str, input_hash: str, gate: GateResult) -> None:
        self.conn.execute(
            "INSERT INTO gate(key,input_hash,verdict,reason,data_json) VALUES(?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET input_hash=excluded.input_hash, "
            "verdict=excluded.verdict, reason=excluded.reason, data_json=excluded.data_json",
            (key, input_hash, gate.verdict, gate.reason, gate.model_dump_json()),
        )
        self.conn.commit()

    # --- sends (idempotency: row present ⇒ already pushed) -------------------
    def is_sent(self, key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM sends WHERE key=?", (key,)).fetchone() is not None

    def mark_sent(self, key: str, platform: str, platform_id: str = "") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO sends(key,platform,platform_id) VALUES(?,?,?)",
            (key, platform, platform_id),
        )
        self.conn.commit()

    def sent_today(self, campaign: str) -> int:
        """Sends recorded today (UTC) for this campaign — drives the daily cap."""
        r = self.conn.execute(
            "SELECT COUNT(*) n FROM sends WHERE date(created_at)=date('now') "
            "AND key IN (SELECT key FROM leads WHERE campaign=?)",
            (campaign,),
        ).fetchone()
        return r["n"]

    # --- cost audit ----------------------------------------------------------
    def log_llm(self, key: str, stage: str, model: str, usage: dict) -> None:
        if not usage:
            return
        self.conn.execute(
            "INSERT INTO llm_calls(key,stage,model,prompt_tokens,completion_tokens) VALUES(?,?,?,?,?)",
            (key, stage, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
        )
        self.conn.commit()

    def token_totals(self, campaign: str) -> dict:
        r = self.conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0) p, COALESCE(SUM(completion_tokens),0) c "
            "FROM llm_calls WHERE key IN (SELECT key FROM leads WHERE campaign=?)",
            (campaign,),
        ).fetchone()
        return {"prompt_tokens": r["p"], "completion_tokens": r["c"]}

    # --- outbox (the final email that would send) ---------------------------
    def save_outbox(self, key: str, draft, verdict: str, variant: str = "signal") -> None:
        self.conn.execute(
            "INSERT INTO outbox(key,subject,body,angle,verdict,edited,variant) VALUES(?,?,?,?,?,0,?) "
            "ON CONFLICT(key) DO UPDATE SET subject=excluded.subject, body=excluded.body, "
            "angle=excluded.angle, verdict=excluded.verdict, edited=0, variant=excluded.variant",
            (key, draft.subject, draft.body, draft.angle, verdict, variant),
        )
        self.conn.commit()

    def get_outbox(self, key: str) -> dict | None:
        r = self.conn.execute(
            "SELECT subject,body,angle,verdict,edited,variant FROM outbox WHERE key=?", (key,)
        ).fetchone()
        return dict(r) if r else None

    # --- A/B outcomes: reply attribution + per-variant stats -----------------
    def mark_replied(self, key: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO replies(key) VALUES(?)", (key,))
        self.conn.commit()

    def ab_stats(self, campaign: str) -> dict:
        """Per variant: drafted / sent / replied, so reply lift can be compared."""
        rows = self.conn.execute(
            "SELECT COALESCE(o.variant,'signal') v, COUNT(*) drafted, "
            "  SUM(CASE WHEN s.key IS NOT NULL THEN 1 ELSE 0 END) sent, "
            "  SUM(CASE WHEN r.key IS NOT NULL THEN 1 ELSE 0 END) replied "
            "FROM outbox o JOIN leads l ON l.key=o.key "
            "LEFT JOIN sends s ON s.key=o.key LEFT JOIN replies r ON r.key=o.key "
            "WHERE l.campaign=? GROUP BY COALESCE(o.variant,'signal')",
            (campaign,),
        ).fetchall()
        return {r["v"]: {"drafted": r["drafted"], "sent": r["sent"] or 0, "replied": r["replied"] or 0} for r in rows}

    def update_outbox(self, key: str, subject: str, body: str) -> None:
        self.conn.execute(
            "UPDATE outbox SET subject=?, body=?, edited=1 WHERE key=?", (subject, body, key)
        )
        self.conn.commit()

    # --- reviews (human approval) -------------------------------------------
    def set_review(self, key: str, decision: str) -> None:
        self.conn.execute(
            "INSERT INTO reviews(key,decision) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET decision=excluded.decision, updated_at=datetime('now')",
            (key, decision),
        )
        self.conn.commit()

    def get_review(self, key: str) -> str | None:
        r = self.conn.execute("SELECT decision FROM reviews WHERE key=?", (key,)).fetchone()
        return r["decision"] if r else None

    # --- email verification (cached by email) -------------------------------
    def get_verify(self, email: str) -> str | None:
        r = self.conn.execute("SELECT status FROM verify WHERE email=?", (email,)).fetchone()
        return r["status"] if r else None

    def save_verify(self, email: str, status: str) -> None:
        self.conn.execute(
            "INSERT INTO verify(email,status) VALUES(?,?) "
            "ON CONFLICT(email) DO UPDATE SET status=excluded.status, updated_at=datetime('now')",
            (email, status),
        )
        self.conn.commit()


def open_store(db_path: str = "data/outreach.db"):
    """Shared backend selector: Mongo when MONGO_URI is set (own DB), else SQLite file."""
    import os
    uri = os.environ.get("MONGO_URI")
    if uri:
        from .store_mongo import MongoStore
        return MongoStore(uri, os.environ.get("MONGO_DB", "outreach"))
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    return Store(db_path)
