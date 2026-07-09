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


def list_sequences() -> list[dict]:
    """The Apollo sequences (emailer_campaigns) approved leads can be added to.

    Returns [{id, name, archived}] so a campaign can pick one instead of pasting an id.
    """
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        return []
    data = _request("POST", "/emailer_campaigns/search", key, {})
    out = []
    for c in data.get("emailer_campaigns", []):
        if c.get("id"):
            out.append({"id": c["id"], "name": c.get("name") or c["id"], "archived": bool(c.get("archived"))})
    return out


def create_sequence(name: str) -> dict:
    """Create a fully-wired Apollo sequence for a campaign, ready for our send path:
    3 auto-email steps on the contact merge fields (first touch, day-3, day-7),
    24/7 schedule, stop-on-reply + stop-on-interested. Returns {id, name}.

    Apollo won't activate a sequence via API — the user flips the Activate toggle
    in Apollo once; surface that in the UI.
    """
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    seq = _request("POST", "/emailer_campaigns", key, {"name": name})
    sid = (seq.get("emailer_campaign") or {}).get("id")
    if not sid:
        raise RuntimeError("Apollo did not return a sequence id")

    def step(pos: int, wait_days: int, body_tag: str, subj_tag: str = ""):
        payload = {"emailer_campaign_id": sid, "type": "auto_email", "position": pos,
                   "wait_mode": "day" if wait_days else "minute",
                   "wait_time": wait_days if wait_days else 30, "exact_datetime": None}
        d = _request("POST", "/emailer_steps", key, payload)
        tmpl = (d.get("emailer_touch") or {}).get("emailer_template_id")
        if tmpl:
            _request("PUT", f"/emailer_templates/{tmpl}", key,
                     {"subject": subj_tag, "body_html": body_tag})

    step(1, 0, "{{contact.email_body}}", "{{contact.email_subject}}")
    step(2, 3, "{{contact.email_body_2}}")
    step(3, 4, "{{contact.email_body_3}}")

    # 24/7 schedule if one exists (any schedule covering all 7 days), else leave default
    try:
        scheds = _request("GET", "/emailer_schedules", key).get("emailer_schedules", [])
        allday = next((x for x in scheds
                       if len((x.get("schedule_hash") or {})) == 7), None)
        flags = {"mark_finished_if_reply": True, "mark_finished_if_interested": True}
        if allday:
            flags["emailer_schedule_id"] = allday["id"]
        _request("PUT", f"/emailer_campaigns/{sid}", key, flags)
    except Exception:
        pass  # sequence is usable without these; user can adjust in Apollo
    return {"id": sid, "name": name}


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


def mailbox_health() -> list[dict]:
    """Per-mailbox deliverability signals straight from Apollo's own scorecard.

    placement: Apollo's inbox-placement test verdict ('unhealthy' is a real warning).
    hard_bounced/spam_blocked: last-week sums from Apollo's rolling score window.
    """
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        return []
    data = _request("GET", "/email_accounts", key)
    out = []
    for a in data.get("email_accounts", []):
        if not (a.get("id") and a.get("email")):
            continue
        score = a.get("deliverability_score") or {}
        out.append({
            "id": a["id"], "email": a["email"], "active": bool(a.get("active")),
            "domain": a["email"].rsplit("@", 1)[-1].lower(),
            "placement": a.get("inbox_placement_test_health_status") or "",
            "warmup_score": a.get("mailwarming_score"),
            "daily_cap": a.get("email_daily_threshold"),
            "hard_bounced": score.get("sum_hard_bounced_count") or 0,
            "spam_blocked": score.get("sum_spam_blocked_count") or 0,
            "domain_health_score": score.get("domain_health_score"),
        })
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


def list_messages(sequence_id: str, limit: int = 200) -> list[dict]:
    """All emailer messages for a sequence (sent + received), raw from Apollo.

    Outbound messages carry email_account_id + type 'outreach_automatic_email';
    threading lives in conversation_id. The API layer groups these into conversations.
    """
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        raise RuntimeError("APOLLO_API_KEY not set")
    out: list[dict] = []
    page = 1
    while len(out) < limit:  # Apollo caps per_page low, so page through
        data = _request("POST", "/emailer_messages/search", key,
                        {"emailer_campaign_ids": [sequence_id], "per_page": 50, "page": page})
        batch = data.get("emailer_messages", []) or []
        out.extend(batch)
        if len(batch) < 50:
            break
        page += 1
    return out[:limit]


def is_inbound(m: dict) -> bool:
    """True when the message came FROM the lead (a reply), not from one of our mailboxes."""
    t = (m.get("type") or "").lower()
    if "reply" in t or "received" in t:
        return True
    # outbound sequence emails always carry the sending account id
    return bool(m.get("from_email")) and not m.get("email_account_id")


def list_replies(sequence_id: str, limit: int = 200) -> list[dict]:
    """Only the received messages (lead replies) — used by the A/B reply sync."""
    return [m for m in list_messages(sequence_id, limit) if is_inbound(m)]


def push_lead(lead: Lead, draft: Draft, campaign: dict, followups: dict | None = None) -> str:
    """Upsert the contact with personalized copy, add it to the sequence. Returns contact id.

    followups: {'subject_2','body_2','subject_3','body_3'} for sequence steps 2 & 3
    (the sequence auto-stops for anyone who replies, so follow-ups only reach silence).
    """
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

    names = [subject_name, body_name]
    fu = followups or {}
    if fu.get("body_2"):
        names += [f"{subject_name}_2", f"{body_name}_2"]
    if fu.get("body_3"):
        names += [f"{subject_name}_3", f"{body_name}_3"]
    fields = _resolve_field_ids(names, key)
    body = personalize.with_signature(draft.body, campaign)   # append the sender footer
    custom = {fields[subject_name]: draft.subject, fields[body_name]: body}
    if fu.get("body_2"):
        custom[fields[f"{subject_name}_2"]] = fu.get("subject_2") or f"Re: {draft.subject}"
        custom[fields[f"{body_name}_2"]] = personalize.with_signature(fu["body_2"], campaign)
    if fu.get("body_3"):
        custom[fields[f"{subject_name}_3"]] = fu.get("subject_3") or f"Re: {draft.subject}"
        custom[fields[f"{body_name}_3"]] = personalize.with_signature(fu["body_3"], campaign)

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
