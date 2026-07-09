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

## KnowDoc AI — document automation *(the logistics/trucking campaign product)*
*(repo: `~/Desktop/Knowdoc` (codename "MailOCR"); domain **knowdoc.ai**; contact knowdocai@knowella.com)*

- **One-liner:** Turn driver and carrier paperwork into clean, audit-ready records — automatically.
- **What it does:** Documents arrive by email or upload (PDFs, invoices, forms); AI OCR extracts and validates the data, splits multi-doc carrier packets (BOLs, PODs, freight bills, rate confirmations), flags exceptions, and delivers structured records via dashboard/webhooks/API — with TMS auto-fill for freight paperwork.
- **Audience:** Logistics/transportation back-office & ops leaders ("Automate Carrier Paperwork at Scale") and safety/compliance leaders ("Keep Safety Records Accurate and Audit-Ready"); also accounting/procurement.
- **Value props:** email-in paperwork read/split/filed automatically · safety certifications + training records tracked with expiry alerts · fewer data-entry errors, faster carrier pay cycles · real-time document status + full audit trail.
- **Goal:** a 15-minute demo · **Link:** https://knowdoc.ai
- **Proof points:** site claims (92% less manual paperwork, 99.8% accuracy, testimonials from "Meridian Logistics"/"FreightCo") are **unverified/illustrative — do NOT cite in emails**. Real integration tenants exist (Trademark TMS; carriers incl. Frozen Food Express, H&M Bay) but are internal references, **[confirm] before naming**.
- **⚠️ Messaging guardrail:** no native DOT/FMCSA/CDL/HOS features found in the product — position as digitizing/tracking *existing* safety and compliance documents, never as built-in DOT/FMCSA compliance.

**`knowledge` block in use (config/logistics-trucking.yaml):** reads inbound paperwork into structured audit-ready records · splits/validates carrier packets, flags exceptions · tracks certifications and training records with expiry alerts and an audit trail.

## Knowella (flagship platform) *(the construction campaign product)*
*(repos: `~/Desktop/customerweb` (Angular app) + `~/Desktop/adminapi` (NestJS); app.knowella.com / knowella.com)*

- **Tagline (verbatim, auth pages):** "Your Platform for Operational Excellence"
- **One-liner:** Build your own safety inspections, checklists, and incident reporting — no code, one platform.
- **What it does:** No-code drag-and-drop App Builder for safety/inspection/compliance apps; frontline reporting (phone + QR-code kiosk logins), scheduling, real-time dashboards, audit logs. AI add-ons: **KnowErgo** (video ergonomic scoring), **Camera Alerts** (CCTV hazard monitoring), **Ella AI** assistant, KnowHealth. (KnowTrain/KnowDoc/KnowRFP/KnowLogistics listed as *coming soon* in-app — don't pitch as shipped from this profile; KnowDoc ships separately, see above.)
- **Audience:** EHS/safety managers, ops leaders, facility managers; industrial/manufacturing/warehousing/construction — anywhere with frontline physical work.
- **Pricing shape:** Platform Subscription base + AI add-on modules, monthly/yearly.
- **Proof points:** none in-repo (authenticated app, not marketing site) — the two real testimonials on the outreach landing page (food manufacturing Director of Safety, food distribution Supply Chain Manager) are the citable ones.
- **`knowledge` block in use (config/knowella-construction.yaml):** no-code builder for inspections/checklists/incident apps · frontline submits via phone/QR, feeding dashboards + audit logs · add-ons include AI ergonomic scoring and CCTV alerts.

## Ella AI — [to profile]
*(module of the platform: "The Knowella AI assistant" — LLM chat, RAG over your docs; product key `prod_U3dT…`)* — profile if it ever gets its own campaign.

---

### ⚠️ Security note (not campaign-related, but worth acting on)
`ai_ergo/.env` has **live secrets committed** (AWS keys, `AUTH_SECRET`, `GROQ_API_KEY`). These should be **rotated and removed from git history** — committed cloud keys are a real exposure.
