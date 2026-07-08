# Knowella product catalog — for campaign setup

Source of truth for the **offer** in outreach campaigns. Each product below maps to a
campaign's `offer` (product / one-liner / value_props / call_to_action / link) and
`knowledge` (the only product claims the writer may state as fact). Add a product here,
then a campaign selling it just references these fields.

> Profiles are built from the product repos + knowella.com. Marketing taglines, pricing,
> and testimonials that live only in `customerweb` / the live site are marked **[confirm]**
> — replace before using them as claims in emails (the engine won't invent them).

---

## ai_ergo — AI ergonomic risk assessment
*(repo: `ai_ergo` / `knowella-ml`; service: `ergo-api`; API: ergoapi.knowella.com)*

- **Marketed name:** Knowella Ergonomics *(exact brand name **[confirm]** — repo is backend-only)*
- **One-liner:** Turn a phone video of a worker into an automated ergonomic injury-risk score.
- **What it does:** Upload a short video of someone working (lifting, reaching, bending); computer-vision pose estimation scores their musculoskeletal-disorder (MSD) risk against recognized standards and returns an annotated video + per-joint angle timelines.
- **Audience:** EHS / safety managers, ergonomists, and operations leaders in **manufacturing, warehousing, logistics, and manual-labor** industries.

**Value props** (concrete outcomes — safe to use as capability, not as proof):
- Score MSD/injury risk from a **short video** — no wearables, no manual stopwatch or protractor scoring.
- Assess **multiple workers in one clip** at once.
- Applies **recognized standards automatically** — REBA, RULA, NIOSH lifting equation, Snook (Liberty Mutual) tables, HSE MAC, WISHA.
- Produces **defensible evidence**: an annotated video + per-second joint-angle timelines for reports and worker feedback.
- **API-driven**, so it plugs into an existing EHS/safety workflow.

- **Goal (where a reply should lead):** a 15-minute demo *(the first email still ends with a soft interest question, not this ask)*
- **Link:** https://knowella.com
- **Proof points / testimonials / metrics:** **none in-repo — [confirm]** from knowella.com / customerweb before citing any number or customer.
- **Signal fit:** OSHA MSD/ergonomic citations, injury logs (OSHA 300), and high-manual-handling operations are strong per-lead signals for this product — prioritize them in research.

**Suggested `knowledge` block for a campaign selling this** (only claims the writer may state as fact):
```
Knowella's ergonomics tool scores worker injury risk from a video using REBA, RULA, NIOSH, Snook, HSE MAC, and WISHA standards.
It assesses multiple workers in one clip and returns an annotated video with joint-angle timelines.
```

---

## Ella AI — [to profile]
*(repo: `backend (Ella AI)`; product key `prod_U3dT…`)* — not yet analyzed.

## App Builder — [to profile]
*(product `prod_Mk0N…`)* — currently the wizard default ("Build safety & compliance workflows without code"). Confirm the full profile.

---

### ⚠️ Security note (not campaign-related, but worth acting on)
`ai_ergo/.env` has **live secrets committed** (AWS keys, `AUTH_SECRET`, `GROQ_API_KEY`). These should be **rotated and removed from git history** — committed cloud keys are a real exposure.
