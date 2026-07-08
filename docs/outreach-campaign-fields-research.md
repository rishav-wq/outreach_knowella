# Campaign fields, targeting filters & missing features — verified research

*Deep research 2026-07-08 · 103 agents · 21 sources → 25 claims verified 3-vote adversarial (23 confirmed, 2 refuted) · plus LIVE probes of Apollo's api_search against OUR key. Companion to [outreach-messaging-research.md](outreach-messaging-research.md).*

---

## Part 1 — What actually makes targeting accurate (verified)

**Micro-segmentation is the #1 lever** *(high, 3-0)*. Instantly's 2026 benchmark (billions of sends): the top factors separating best-performing campaigns are micro-segmentation, problem-focused messaging, frequent A/B testing. Corroborated by Woodpecker (20M emails): ~50-recipient tight cohorts got ~5.8% replies vs ~2.1% for 1,000+ blasts. **Design implication: nudge one narrow persona × size-band × geography per campaign, not broad OR-lists.** (Vendor-observational, not controlled; no isolated lift number.)

**Company size is the single most predictive field we expose** *(high, 3-0)*. Belkins (7.53M emails): 0-10 employee companies reply at 0.72% — 3x+ the 0.22% of 10,000+ enterprises, near-linear gradient between. The gradient generalizes; the absolute percentages don't. **Make employee-size ranges prominent.**

**Free keywords are noisy — Apollo says so itself** *(high, 3-0)*. Apollo's own KB warns broad keywords ("manufacturing") match companies that merely *mention* the term. Keep keywords but warn in-UI; prefer structured filters where possible.

**REFUTED — do not build on these:**
- ✗ *"Founders reply 0.57% > C-level 0.42% > VPs 0.32%, so target lower/higher on the org chart"* (0-3). No verified seniority reply gradient exists. Seniority is still worth exposing for **precision** (cutting juniors/assistants), just not as a reply-rate play.
- ✗ *"Lower send volume itself correlates with higher reply rates"* (1-2). Volume conflates with targeting quality.

## Part 2 — Missing features, ranked (verified where possible)

1. **Multi-step follow-up sequences** *(high, 3-0 — the largest quantified gap)*. Follow-ups generate **42% of all replies** (58% from step 1); 4-7 touchpoints optimal; Backlinko: a single follow-up lifts replies ~65.8%. Our single first-touch forfeits ~40% of replies. → Wire drafting/approval for follow-up steps in the Apollo sequence.
2. **Unsubscribe + suppression compliance** *(high, 3-0 — a mailbox-provider MANDATE, not a feature)*. Since Feb 2024 Google/Yahoo bulk-sender rules require one-click unsubscribe (RFC 8058) honored within 48h for 5,000+/day senders; baseline SPF/DKIM/spam-rate rules apply to ALL senders; Outlook added parallel rules May 2025. Enforcement now includes hard 550 rejections. → Suppression list + unsubscribe handling before scale.
3. **Reply classification** (interested / not-interested / OOO) — needed to stop sequences on reply and compute real metrics. *(ranking judgment-based)*
4. **Bounce handling + domain-health monitoring** (spam rate, SPF/DKIM/DMARC — same Google/Yahoo rules).
5. **Outcome analytics** — positive-reply rate and meetings booked, the numbers buyers actually judge tools by (we count total replies only).

*Deprioritized for our model (own-mailbox, human-approved, low-volume): automated warmup (Google banned warmup pools' API access in 2023 and treats artificial engagement as spam-signal), inbox rotation, spintax.*

## Part 3 — Apollo filter coverage: docs vs LIVE probes on our key

Docs (all live-verified 2026-07-08): api_search needs a master key, consumes **no credits** for searching, returns no emails (reveal costs credits), 50k display cap. `person_seniorities` has exactly 11 values: owner, founder, c_suite, partner, vp, head, director, manager, senior, entry, intern. `contact_email_status`: verified / unverified / likely to engage / unavailable. Docs list NO department/industry-taxonomy/funding/exclusion params on People Search — **but our live probes show several undocumented params ARE honored on our plan** (probe = result-count changes, 2026-07-08):

| Filter | Docs | LIVE on our key | Note |
|---|---|---|---|
| person_titles / include_similar_titles | ✓ | ✓ (in use) | |
| person_seniorities | ✓ | ✓ HONORED | 11 enumerated values |
| person_functions | ✗ | ✓ HONORED | `person_departments` is silently ignored — use functions |
| person_not_titles (title exclude) | ✗ | ✓ HONORED | undocumented but works |
| person_locations vs organization_locations | ✓ | ✓ both | genuinely different results — expose as two fields |
| organization_num_employees_ranges | ✓ | ✓ (in use) | most predictive field |
| revenue_range[min/max] | ✓ | ✓ HONORED | |
| q_organization_keyword_tags (+ not_) | ✗ | ✓ (in use) | our pull already relies on it |
| q_keywords free text | ✓ | ✓ HONORED | noisy — warn |
| contact_email_status | ✓ | ✓ HONORED | verified-only pull = fewer wasted reveal credits + bounces |
| q_organization_job_titles / organization_num_jobs_range | ✓ | ✓ HONORED | hiring signals as a FILTER (e.g. 5,369 US cos. hiring drivers w/ a safety director) |
| organization_latest_funding_stage_cd | ✗ (Org Search only) | ✓ HONORED | works on people search too |
| currently_using_any_of_technology_uids | ✓ | ✓ HONORED | + documented exclusion variant |
| SIC/NAICS, buying intent, zip-radius | UI only | — | not exposed to the API |

Plan-gating caveat: Apollo gates advanced filters by plan and doesn't enumerate API gating — **feature-detect at runtime** (degrade gracefully) since these probes reflect today's plan.

## The build list (prioritized)

**Wizard/Settings audience fields** — add: **seniority** multi-select (11 values), **email status** default verified+likely-to-engage, **person vs company-HQ location** as two fields, employee-size stays prominent; advanced (collapsed): revenue range, hiring-signals toggle ("actively hiring driver/safety roles" — perfect for the EHS/fleet wedge), technographics, title-exclude. Keep title include + keywords (with noise warning). Keep suppression/customer-domain exclusions client-side post-fetch.

**Features next, in order:** ① multi-step follow-up drafting/approval → ② unsubscribe/suppression compliance → ③ reply classification → ④ bounce/domain health → ⑤ positive-reply & meetings analytics.

## Open questions
- Optimal absolute segment size per campaign (evidence suggests <200 beats 1,000+, but confounded) — instrument our own analytics.
- Does Apollo's sequences API expose stop-on-reply control + bounce/unsubscribe webhooks we can consume (needed for #1/#2/#3)?
- Which plan-gated filters (intent especially) return data vs 403 as our plan changes.
