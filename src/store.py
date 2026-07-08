"""State store — the backbone. Persisted, resumable, idempotent.

MongoDB is the one and only backend (MONGO_URI required). Each lead is a document
with a status; each stage's output is cached keyed by an `input_hash`, so re-running
a stage with unchanged inputs is a no-op (incremental build). Crash-resume and cheap
prompt iteration both fall out of this for free. Implementation: store_mongo.MongoStore.
"""
from __future__ import annotations

import hashlib
import json
import os

from .store_mongo import MongoStore

# The store interface — pipeline/review type-hint against this name.
Store = MongoStore

_store: MongoStore | None = None  # process-wide singleton: an Atlas connect+ping costs ~5s, a query 0.05s


def hash_inputs(*parts) -> str:
    """Stable short hash of arbitrary JSON-able inputs (cache-invalidation key)."""
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def open_store():
    """The shared MongoStore. Cached for the process — MongoClient is thread-safe and
    pools connections, so reconnecting per call would add seconds to every request."""
    global _store
    if _store is None:
        uri = os.environ.get("MONGO_URI")
        if not uri:
            raise RuntimeError("MONGO_URI is not set — the app needs its MongoDB. "
                               "Set it in .env (see .env.example).")
        _store = MongoStore(uri, os.environ.get("MONGO_DB", "outreach"))
    return _store
