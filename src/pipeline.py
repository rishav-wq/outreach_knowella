"""Orchestration — advance each lead through the state machine.

    NEW → RESEARCHED → DRAFTED → GATED ─┬─ pass/fallback → QUEUED → SENT
                                        └─ drop ─────────→ DROPPED

Every stage is idempotent and cached by an input_hash, so re-running is cheap and
crash-safe: unchanged inputs return the stored output without re-paying for it.
"""
from __future__ import annotations

from datetime import datetime

from .engine import personalize, quality_gate
from .engine import research as research_engine
from .integrations import apollo_send, email_verify, enrich
from .models import Draft, GateResult, Lead, Research
from .store import Store, hash_inputs


def send_guard(store: Store, cfg: dict) -> str:
    """Deliverability guardrails checked before every push. Returns a human-readable
    reason to hold the send, or '' when sending is allowed.

    sending.window: {start_hour, end_hour, weekdays_only} — local time.
    sending.daily_cap: max pushes per day (0/absent = unlimited).
    """
    send_cfg = cfg.get("sending") or {}
    win = send_cfg.get("window") or {}
    now = datetime.now()
    if win.get("weekdays_only") and now.weekday() >= 5:
        return "outside send window (weekends off)"
    start, end = win.get("start_hour"), win.get("end_hour")
    if start is not None and end is not None and not (int(start) <= now.hour < int(end)):
        return f"outside send window ({int(start):02d}:00-{int(end):02d}:00)"
    cap = int(send_cfg.get("daily_cap") or 0)
    if cap and store.sent_today(cfg["name"]) >= cap:
        return f"daily cap reached ({cap}/day)"
    return ""


def research_hash(lead: Lead, cfg: dict) -> str:
    # bump the rev string whenever research logic changes (invalidates the cache)
    return hash_inputs("research-rev3", lead.key)


def variant_for(lead_key: str, cfg: dict) -> str:
    """A/B assignment: 'signal' (grounded, signal-led) vs 'plain' (control, no signal).
    Deterministic per lead so re-runs are stable. Off unless experiment.enabled — then
    control_ratio of leads get the plain control opener so reply lift can be measured."""
    exp = cfg.get("experiment") or {}
    if not exp.get("enabled"):
        return "signal"
    ratio = float(exp.get("control_ratio", 0.5))
    bucket = int(hash_inputs("ab", lead_key), 16) % 1000 / 1000.0
    return "plain" if bucket < ratio else "signal"


def draft_hash(research: Research, cfg: dict, variant: str = "signal") -> str:
    return hash_inputs(
        "draft-rev8",  # bump when the personalize prompt/format changes (invalidates drafts)
        variant,       # signal vs plain control cache separately
        research.model_dump(),
        cfg.get("offer"),
        cfg.get("voice"),
        (cfg.get("models") or {}).get("personalize"),
    )


def ensure_verified(store: Store, lead: Lead, cfg: dict) -> str:
    """Cached email check. 'unknown' when no email or no verifier key (never blocks)."""
    if not lead.email or not email_verify.has_key():
        return "unknown"
    status = store.get_verify(lead.email)
    if status is None:
        status = email_verify.verify(lead.email)
        store.save_verify(lead.email, status)
    return status


def ensure_research(store: Store, lead: Lead, cfg: dict) -> Research:
    h = research_hash(lead, cfg)
    cached = store.get_research(lead.key, h)
    if cached is not None:
        return cached
    res, usage, model = research_engine.research_lead(lead, cfg)
    store.save_research(lead.key, h, res)
    store.log_llm(lead.key, "research", model, usage)
    return res


def ensure_draft(store: Store, lead: Lead, research: Research, cfg: dict, dh: str, variant: str = "signal") -> Draft:
    cached = store.get_draft(lead.key, dh)
    if cached is not None:
        return cached
    draft, usage, model = personalize.write_email(lead, research, cfg, variant)
    store.save_draft(lead.key, dh, draft)
    store.log_llm(lead.key, "personalize", model, usage)
    return draft


def ensure_gate(store: Store, lead: Lead, draft: Draft, research: Research, cfg: dict, dh: str) -> GateResult:
    # bump the rev string whenever the gate's logic/prompt changes (invalidates cache)
    gh = hash_inputs("gate-rev2", dh)
    cached = store.get_gate(lead.key, gh)
    if cached is not None:
        return cached
    gate, usage, model = quality_gate.check(draft, lead, research, cfg)
    store.save_gate(lead.key, gh, gate)
    store.log_llm(lead.key, "gate", model, usage)
    return gate


def advance(store: Store, lead: Lead, cfg: dict, dry_run: bool, require_review: bool = True) -> dict:
    # Stage -1: do-not-contact list (compliance) — before spending anything
    if lead.email and store.is_suppressed(lead.email):
        store.set_status(lead.key, "suppressed")
        return {"lead": lead, "verdict": "suppressed", "reason": "on the do-not-contact list", "draft": None}

    # Stage 0: email verification — drop dead addresses before spending research tokens
    vstatus = ensure_verified(store, lead, cfg)
    block = {"undeliverable"}
    if (cfg.get("verify") or {}).get("block_risky"):
        block.add("risky")
    if vstatus in block:
        store.set_status(lead.key, "invalid")
        return {"lead": lead, "verdict": "invalid", "reason": f"email {vstatus}", "draft": None}

    res = ensure_research(store, lead, cfg)
    store.set_status(lead.key, "researched")

    # A/B arm: assigned ONCE, then sticky. Changing the experiment slider only
    # affects leads that haven't been drafted yet — an already-reviewed draft never
    # silently flips arms (and regenerates) because the ratio moved.
    _ob = store.get_outbox(lead.key) or {}
    variant = _ob.get("variant") or variant_for(lead.key, cfg)
    dh = draft_hash(res, cfg, variant)
    draft = ensure_draft(store, lead, res, cfg, dh, variant)
    store.set_status(lead.key, "drafted")

    gate = ensure_gate(store, lead, draft, res, cfg, dh)
    store.set_status(lead.key, "gated")

    if gate.verdict == "drop":
        store.set_status(lead.key, "dropped")
        return {"lead": lead, "verdict": "drop", "reason": gate.reason, "draft": None}

    final = gate.draft or draft
    ob = store.get_outbox(lead.key)
    if not (ob and ob.get("edited")):
        store.save_outbox(lead.key, final, gate.verdict, variant)  # refresh unless manually edited

    # follow-ups (sequence steps 2 & 3): drafted from the final first email, cached by
    # fu_hash so they regenerate only when the first email changes and aren't hand-edited.
    ob = store.get_outbox(lead.key) or {}
    fuh = hash_inputs("fu-rev2", final.subject, final.body, variant)
    if ob.get("fu_hash") != fuh and not ob.get("edited"):
        body2, body3, usage, model = personalize.write_followups(
            lead, res, cfg, final.subject, final.body, variant)
        if body2 and body3:
            store.save_followups(lead.key, f"Re: {final.subject}", body2,
                                 f"Re: {final.subject}", body3, fuh)
            store.log_llm(lead.key, "followups", model, usage)

    if dry_run:
        store.set_status(lead.key, "queued")
        return {"lead": lead, "verdict": gate.verdict, "reason": gate.reason, "draft": final}

    # send path — the only irreversible step. Only approved leads are pushed;
    # undecided ones stay queued (so a send doesn't sweep up un-reviewed drafts).
    decision = store.get_review(lead.key)
    if require_review and decision != "approved":
        if decision == "rejected":
            store.set_status(lead.key, "rejected")
            return {"lead": lead, "verdict": "rejected", "reason": "rejected in review", "draft": final}
        store.set_status(lead.key, "queued")
        return {"lead": lead, "verdict": "queued", "reason": "awaiting approval", "draft": final}

    # approved: deliverability guardrails hold the send (lead stays queued, nothing lost)
    guard = send_guard(store, cfg)
    if guard:
        store.set_status(lead.key, "queued")
        return {"lead": lead, "verdict": "held", "reason": guard, "draft": final}

    # ensure we have an email (enrich from the domain if it's missing)
    if not lead.email:
        found = enrich.find_email(lead.company_domain, lead.first_name, lead.last_name)
        if found:
            lead.email = found
            store.update_lead(lead)
    if not lead.email:
        store.set_status(lead.key, "queued")
        return {"lead": lead, "verdict": "no_email", "reason": "no email found — add one to send", "draft": final}

    # optionally require a positively verified address before anything leaves
    if (cfg.get("verify") or {}).get("require_deliverable"):
        vstatus = ensure_verified(store, lead, cfg)
        if vstatus != "deliverable":
            store.set_status(lead.key, "queued")
            return {"lead": lead, "verdict": "held",
                    "reason": f"email not verified deliverable ({vstatus})", "draft": final}

    # push the reviewed/edited email — the outbox is the source of truth for sending
    outbox = store.get_outbox(lead.key)
    send_draft = (Draft(subject=outbox["subject"], body=outbox["body"], angle=outbox.get("angle", ""))
                  if outbox else final)
    if store.is_suppressed(lead.email):   # final gate — suppression added after approval
        store.set_status(lead.key, "suppressed")
        return {"lead": lead, "verdict": "suppressed", "reason": "on the do-not-contact list", "draft": final}
    if not store.is_sent(lead.key):
        fu = {k: (outbox or {}).get(k, "") for k in ("subject_2", "body_2", "subject_3", "body_3")}
        pid = apollo_send.push_lead(lead, send_draft, cfg, followups=fu)
        store.mark_sent(lead.key, "apollo", pid or "")
    store.set_status(lead.key, "sent")
    return {"lead": lead, "verdict": "sent", "reason": "pushed", "draft": send_draft}


def run(store: Store, cfg: dict, dry_run: bool = True, limit: int | None = None,
        require_review: bool = True) -> list[dict]:
    leads = store.leads(cfg["name"])
    if limit:
        # Advance a BATCH of not-yet-processed leads first, so "run 25" drafts 25
        # fresh leads (the expensive work), not the same first 25 every time. Falls
        # back to the head of the list (cheap cached re-run) if none are new.
        fresh = store.leads(cfg["name"], "new")
        leads = (fresh or leads)[:limit]
    results = []
    for lead in leads:
        try:
            results.append(advance(store, lead, cfg, dry_run, require_review))
        except Exception as e:  # one bad lead must not kill the whole run
            store.set_status(lead.key, "error")
            results.append({"lead": lead, "verdict": "error", "reason": str(e), "draft": None})
    return results
