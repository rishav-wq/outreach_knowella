"""Sending platform — Apollo sequences.

Sends approved leads through your own Apollo mailboxes. Pushes an approved lead
+ its personalized copy into an Apollo sequence and sends from a configured
mailbox.

Apollo sequences are template-based, so per-lead copy rides in via CONTACT
custom fields that the sequence's email step references as merge tags:
    subject: {{email_subject}}      body: {{email_body}}
Create those two contact custom fields in Apollo, reference them in the
sequence's email step, then set in the campaign config:
    sending:
      platform: apollo
      sequence_id: <emailer_campaign id>
      mailbox_id:  <email_account id to send from>
      subject_field: "email_subject"   # contact custom-field NAMEs (resolved to ids here)
      body_field:    "email_body"

Send flow per lead: upsert the contact with the copy in its custom fields →
add the contact to the sequence with the send-from mailbox. Only the second
call actually starts sending, so validate with a single test contact first.
"""
from __future__ import annotations

import os

import httpx

from ..engine import personalize
from ..models import Draft, Lead

BASE = "https://api.apollo.io/api/v1"
_field_cache: dict[str, str] = {}   # custom-field name -> id (per process)


def has_key() -> bool:
    return bool(os.environ.get("APOLLO_API_KEY"))


def _hdr(key: str) -> dict:
    return {"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key}


def _request(method: str, path: str, key: str, payload: dict | None = None) -> dict:
    r = httpx.request(method, f"{BASE}{path}", json=payload, headers=_hdr(key), timeout=60.0)
    if r.status_code >= 400:
        try:
            reason = r.json().get("error") or r.text[:250]
        except Exception:
            reason = r.text[:250]
        raise RuntimeError(f"Apollo {method} {path} failed [{r.status_code}]: {reason}")
    return r.json()


def _resolve_field_ids(names: list[str], key: str) -> dict[str, str]:
    """Map contact custom-field names -> ids (cached). Names are what you set in config."""
    need = [n for n in names if n and n not in _field_cache]
    if need:
        data = _request("GET", "/typed_custom_fields", key)
        for f in data.get("typed_custom_fields", []):
            if f.get("name"):
                _field_cache[f["name"]] = f.get("id")
    missing = [n for n in names if n and not _field_cache.get(n)]
    if missing:
        raise RuntimeError(f"Apollo custom field(s) not found: {missing}. "
                           f"Create them as contact fields in Apollo and reference them in the sequence template.")
    return {n: _field_cache[n] for n in names if n}


def _find_contact_id(email: str, key: str) -> str | None:
    data = _request("POST", "/contacts/search", key, {"q_keywords": email, "per_page": 1})
    for c in data.get("contacts", []):
        if (c.get("email") or "").lower() == email.lower():
            return c.get("id")
    return None


def list_mailboxes() -> list[dict]:
    """The Apollo mailboxes (email accounts) available to send from.

    Returns [{id, email, active}] so a campaign can pick which one sends.
    """
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        return []
    data = _request("GET", "/email_accounts", key)
    out = []
    for a in data.get("email_accounts", []):
        if a.get("id") and a.get("email"):
            out.append({"id": a["id"], "email": a["email"], "active": bool(a.get("active"))})
    return out


# --- read side: sequence stats + replies (powers Analytics + Inbox) ----------
def sequence_stats(sequence_id: str) -> dict:
    """The Apollo sequence's delivery stats (unique_delivered/opened/replied/…)."""
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    data = _request("POST", "/emailer_campaigns/search", key, {})
    for c in data.get("emailer_campaigns", []):
        if c.get("id") == sequence_id:
            return c
    return {}


def list_replies(sequence_id: str, limit: int = 50) -> list[dict]:
    """Received messages (replies) for a sequence — the Inbox feed. Empty until leads reply."""
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    data = _request("POST", "/emailer_messages/search", key,
                    {"emailer_campaign_ids": [sequence_id], "per_page": limit})
    return data.get("emailer_messages", []) or []


def get_thread(thread_id: str, limit: int = 50) -> list[dict]:
    """All messages in one conversation thread, for the conversation view."""
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    data = _request("POST", "/emailer_messages/search", key, {"q_keywords": thread_id, "per_page": limit})
    return data.get("emailer_messages", []) or []


def push_lead(lead: Lead, draft: Draft, campaign: dict) -> str:
    """Upsert the contact with personalized copy, add it to the sequence. Returns contact id."""
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    send = campaign.get("sending") or {}
    seq_id = send.get("sequence_id")
    mailbox_id = send.get("mailbox_id")
    subject_name = send.get("subject_field") or "email_subject"
    body_name = send.get("body_field") or "email_body"
    if not seq_id or not mailbox_id:
        raise RuntimeError("Apollo sending needs sending.sequence_id and sending.mailbox_id in the campaign config")
    if not lead.email:
        raise RuntimeError(f"lead {lead.full_name} has no email — cannot send")

    fields = _resolve_field_ids([subject_name, body_name], key)
    body = personalize.with_signature(draft.body, campaign)   # append the sender footer
    custom = {fields[subject_name]: draft.subject, fields[body_name]: body}

    # 1) upsert the contact with the copy in its custom fields
    cid = _find_contact_id(lead.email, key)
    body = {
        "first_name": lead.first_name, "last_name": lead.last_name,
        "organization_name": lead.company, "email": lead.email,
        "typed_custom_fields": custom,
    }
    if cid:
        _request("PUT", f"/contacts/{cid}", key, body)   # update existing (POST 404s)
    else:
        created = _request("POST", "/contacts", key, body)
        cid = (created.get("contact") or {}).get("id") or created.get("id")
    if not cid:
        raise RuntimeError("Apollo contact upsert returned no id")

    # 2) add the contact to the sequence, sending from the chosen mailbox (this starts sending)
    _request("POST", f"/emailer_campaigns/{seq_id}/add_contact_ids", key, {
        "contact_ids": [cid],
        "emailer_campaign_id": seq_id,
        "send_email_from_email_account_id": mailbox_id,
    })
    return cid
