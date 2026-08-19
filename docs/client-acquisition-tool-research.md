# What to build next for getting clients — discovery research

*Researched 2026-08-15 · four parallel web scans (trends, problem mining, revenue benchmarks, vertical gaps) · builds on `outreach-market-research.md`, `prospect-signals-research.md`, `outreach-messaging-research.md`, `directory-listings.md`.*

**The question:** we built an outreach app; cold Apollo lists measured 4,422 leads → 9 replies → 0 meetings (0.21%). What client-getting tool is actually worth building next — for Knowella first, and possibly as a sellable product?

---

## The honest headline first

Three independently verified facts frame everything below:

1. **The motion that produced our 0.21% is structurally dead, but cold email isn't.** Industry averages fell ~8.5% (2019) → ~3.4% (2026, Instantly's own sending data); Belkins' strict-count agency average is 0.45%, so we're at half the agency average, not 1/20th. Google/Yahoo's 2024 bulk-sender rules now *reject* (not filter) non-compliant mail, Google applies prospecting-pattern scrutiny even to low-volume senders, and LinkedIn cut Open InMail from ~800 to <100/mo. What died — with multi-source confirmation — is exactly what we ran: scraped list, volume-first, generic offer. Signal-triggered micro-campaigns still report 9–18% replies (vendor-reported; treat as direction, not number).
2. **Buyers moved to AI answers faster than anyone expected.** G2's own survey: **51% of B2B software buyers now start vendor research in an AI chatbot, up from 29% in April 2025** — 22 points in 11 months, the steepest behavior curve in this research. Pew (primary, n=900): when an AI Overview appears, clicks on traditional results drop 15%→8%. Shortlists shrank from 3.2 to 2.5 names, largely decided before any sales contact. And the DerivateX citation study (2026, 233 recommendations across 40 categories) found **G2 and Capterra got ~zero ChatGPT citations — 82% go to independent/niche content**. The AI-visibility surface is niche blogs, lookup tools, and citable pages, not review-site badges.
3. **Public-records data has a proven pricing ladder, and our corner of it is nearly empty.** Raw records floor at $0.08–0.10/lead (Apify scrapers, CSV resellers). The same records packaged as *timely, scored, workflow-ready alerts* command $300–600/mo (Shovels.ai on permits, ConstructConnect) up to $10–30K/yr (GovSpend, GovWin — both PE-owned, i.e. durable boring cash flow). Hazel Analytics (restaurant inspections) exited to Ecolab. In *our* data — OSHA/EPA/FMCSA enforcement — exactly one purpose-built seller exists.

Also verified: the fully-autonomous AI SDR tier kept collapsing (11x scandal; 50–70% churn reports), and the surviving architecture is **AI research + human-approved sends — the one we already built**. The pipeline isn't the problem. What we feed it is.

---

## Scan digests (what each found)

### Trends scan
- **GEO tooling is a funded knife-fight at the horizontal layer**: Profound $96M Series C at $1B valuation (Feb 2026), $300M+ into the category in a year, Peec AI $0→~$10M ARR in ~16 months, entry tiers already collapsing to $20–29/mo. Dozens of prompt-tracking dashboards with shallow differentiation; SEO veterans call much of it repackaged SEO. **Don't build a GEO dashboard.** The open ground is *being the cited thing* in a vertical, not measuring citation.
- **Free interactive tools still convert and gained a new superpower**: interactive lead magnets beat gated PDFs ~2.4x (vendor data, directionally unanimous); ROI calculators on bottom-funnel traffic report 8–20% conversion. New in 2026: an ungated free tool is a **GEO asset** — exactly what ChatGPT/Perplexity cite when someone asks "how do I check X". Gated PDFs are invisible to LLMs. Regulated-industry utilities (OSHA fine exposure, FMCSA score lookup) are near-empty as lead-gen plays.
- **Signal-based selling won the argument but standard signals are saturated**: Clay ($150M ARR, $5B valuation) admits funding/job-change triggers are "background noise" because everyone fires on them. Practitioner consensus: **stack 2–3 corroborating signals** — which today requires Clay plumbing plus a $5–10K/mo GTM engineer. Nobody ships pre-stacked, industry-specific signals as turnkey product.

### Problem-mining scan
- **Warm beats cold 8–10x** — the most-replicated number set found (referral/intro conversion ~11–25% vs 0.2–2% cold; close 14.6% vs 1.7%). But warm-intro *software* keeps failing (see below) because intro supply is human, not tooling.
- **Loudest priced pains with weak tooling**: SMB-priced intent signals ("$60K/yr ZoomInfo used like a $200/mo tool"); GEO panic (agencies charging $2–15K/mo retainers, $500–2K one-time audits for largely automatable probing); LinkedIn ghostwriting at $2–10K/mo with a 20–40% premium in regulated niches because generic AI fails domain fluency; GTM-engineer agencies at $5–8K/mo median retainers — **companies pay $60–120K/yr for humans to operate the plumbing we built for ourselves**.
- **Trade shows are still the #1-rated lead source for our exact audience**, and the canonical failure is follow-up ("85% of leads are garbage", follow-up starts too late). Nothing productizes badge-scan → enrich → signal-score → approved follow-up for vertical vendors.

### Revenue-benchmark scan (category ranking by willingness-to-pay × room for a solo vertical player)
| Rank | Category | Willingness to pay | Room for solo player |
|---|---|---|---|
| 1 | **Public-records vertical alerts** | $300–600/mo SMB → $10–30K/yr; PE/strategic exits | **High** — quote-gated dinosaurs above, $0.10/lead scrapers below; the $99–499/mo alert middle is thin |
| 2 | Signal/intent platforms | Very high (Clay $150M ARR; UserGems $33–120K/yr) | Medium — giants own workflow; solo space is $40–350/mo single-signal tools |
| 3 | GEO / AI visibility | High, rising fast | Medium/low and closing — 30+ funded entrants |
| 4 | Interactive lead-magnet builders | Medium, cheap ($20–150/mo; Interact ~$5.3M ARR bootstrapped) | Medium — distribution-bound lifestyle business |
| 5 | Review/listing management | Low; the money goes to G2 itself | Low — single-gatekeeper risk (G2 bought Capterra/GetApp/Software Advice, Feb 2026) |
| 6 | Warm-intro/relationship graphs | Low — Commsor raised $66M, wound down, sold to The Swarm | Low — the constraint is human intro supply. **Avoid.** |

### Vertical-gap scan (the decisive one)
- **A direct incumbent validates the enforcement-feed price point**: [OSHAlert](https://www.oshalert.com) sells nightly OSHA-citation lead digests with verified phone numbers to safety consultants, trainers, and insurance brokers at **$49/mo (1 state) / $149 (5 states) / $399 (national)** — and shows no founding date, no testimonials, no customer counts. New, pre-traction, **OSHA-only**.
- **Nobody sells EPA-penalty leads. Nobody sells FMCSA-intervention leads.** Carrier Details built a whole FMCSA-resale business (API, prospect lists for insurers/factoring) but every commercial feed targets *new authority*; the *just-downgraded carrier* slice — the one an entire corrective-action-plan consulting industry (Foley, J.J. Keller, My Safety Manager) monetizes — is unserved. Six paid Apify FMCSA scrapers + OSHA scrapers marketed for "safety, insurance, vendor-risk leads" = people paying to DIY what no product offers.
- **The buyer pool is real**: ~51,691 US occupational-safety-services firms (IBISWorld 2025, $11.1B market, growing), 247 EHS products on G2 (only ~21 get Verdantix attention), plus PPE distributors ($21.1B industry), insurance brokers with loss-control practices, PEOs, staffing.
- **No vertical GEO specialist serves EHS/trucking-compliance** — only a manufacturing-adjacent agency (RH Blake) exists.
- LinkedIn-engagement capture is **not** a gap: Trigify/Teamfluence/HeyReach serve it horizontally at $79–549/mo, all riding ToS-violating access. A vertical wrapper adds little.

---

## The five ideas, ranked (five-filter score)

### Idea 1: Enforcement lead feed — "companies that just got cited" (WINNER, 5/5)
**One-liner:** Weekly enriched leads: employers just hit by OSHA, EPA, or FMCSA.
**Revenue model:** $99/mo one state+agency → $299/mo multi-state → $499/mo national all-agency + API. (OSHAlert anchors $49–399; we price above it on coverage + enrichment.)
**Target customer:** The owner of a 3–15-person safety-consulting or training firm — one of ~51,691 US firms — plus insurance loss-control teams and the 226 non-leader EHS vendors.
**First dollar path:** Generate a real sample digest (last 7 days of Texas OSHA citations, contact-enriched via our Apollo plan) → put it in front of safety consultants sourced from ASSP/NAEM directories and the 130K-member EHS LinkedIn group → Stripe link at $99/mo.
**Build estimate:** Demo in 1 day (OSHA ingestion already runs; enrichment exists). Sellable v1 in 2–3 weeks (state filters, digest email, Stripe, ECHO bulk import). FMCSA interventions phase 2.
**Monthly revenue potential at 6 months:** $3–10K MRR (30–70 subscribers) — judged against OSHAlert's validated pricing and a 50K-firm pool reachable through the exact communities we already mapped in `monitoring-sources.md`.
**Filters:** Profitability ✓ (validated price × large pool). Comprehension ✓ (ingest public records → enrich → digest → subscription). Replicability ✓ (60% already built). Automation 9/10 ✓ (polling + enrichment + digest are all machine work). Speed ✓ (demo tomorrow, <30 days to first dollar).
**Demand validation:** OSHAlert's pricing page is a competitor-funded market test; six paid Apify FMCSA scrapers; consultants coached to mine EPA data manually. **Why now:** enforcement data is machine-readable, incumbent is embryonic, and AI-spam saturation makes "something real just happened to you" the only opener that still lands.
**The strategic kicker:** Knowella is customer zero — every feed item is also a lead for our own campaigns, measured against the 0.21% baseline through the Sources page we already built.

### Idea 2: Free public lookup tool — "check any company's safety record" (4/5 as a product; highest leverage for Knowella itself)
**One-liner:** Ungated OSHA/FMCSA record lookup + fine-exposure calculator on knowella.com.
**Why it matters:** HubSpot-Grader mechanics (self-qualifying visitors: only safety-conscious people check safety records) + the 2026 twist — ungated tools get cited by ChatGPT/Perplexity when a safety manager asks "how do I check our OSHA history," and 51% of buyers now start there. OSHARecord already proves the SEO mechanics with per-company pages but doesn't convert to anything.
**Fails filter 5 as a standalone business** (no direct first dollar) — but as Knowella demand-gen it's the highest-leverage build, and it is **the distribution engine for Idea 1**: per-company public pages rank/get cited → visitors who look up *other* companies' records are consultants and brokers → the exact buyer of the paid feed.
**Build estimate:** 1–2 weeks (data already ingested; static-generated company pages + calculator).

### Idea 3: Vertical GEO for EHS/compliance software (3.5/5)
**One-liner:** Make EHS vendors the answer ChatGPT gives; audit + fix + monitor.
**Reality check:** Spend is proven ($500–2K audits, $500–1,500/mo monitoring, $2–15K/mo retainers) and the vertical is empty — but it's a *service* (automation ~6/10), and we'd be selling to competitors while needing the capability ourselves. **Right move:** apply it to Knowella first (that's largely Idea 2 + citable content + the directory listings already mapped), keep productization as a later option once we can show "here's how we made Knowella the cited answer."

### Idea 4: Trade-show follow-up machine (3/5)
Badge scan → enrich → signal-score → human-approved sequences. Real, painful, unserved — and trade shows are the #1 channel for our audience. But: seasonal demand, requires selling into event workflows we don't inhabit, and the pipeline it needs is... our existing app plus Idea 1's enrichment. Park it; it may fall out of the same codebase later.

### Idea 5: Warm-path graph for industrial verticals (2/5)
The demand pattern is loud (warm converts 8–10x) but the category is a graveyard — Commsor raised $66M and wound down; survivors are $99/mo tools or data-API pivots. The constraint is people's willingness to make intros, not software. **Avoid building; harvest the insight instead** — track champion job changes and association overlap as *signals* inside Idea 1.

---

## Validation of the winner (six questions)

**Q1 — Demand reality:** People pay today: OSHAlert charges $49–399/mo for the OSHA slice alone; Apify actors sell per-run OSHA/FMCSA scrapes "to rank safety, insurance and vendor-risk leads"; Carrier Details runs a business on FMCSA resale; pest-control firms market "failed your inspection?" services with no data product behind them.

**Q2 — Status quo:** Manual OSHA Establishment Search lookups, quarterly IMIS refreshes, Google Alerts, $99 one-time carrier CSVs, or paying a VA/scraper. Cost: hours per week and — worse — being late, because the value of a citation lead decays with the contest window.

**Q3 — Desperate specificity:** The principal of a small Texas safety-consulting firm. An employer cited this week has **15 business days to contest** and needs an informal conference strategy and abatement plan *now*. Every day late, the deal goes to whoever called first, or to nobody. The consultant's alternative is refreshing a government website.

**Q4 — Narrowest wedge:** One weekly email: newly cited employers in one state, violation type + penalty + decision-maker contact. $99/mo. No dashboard, no API, no multi-agency — that all comes later.

**Q5 — Observation test:** The consultant opens the digest and immediately asks: "who do I call, and is the fine big enough to matter?" — so contact enrichment and penalty-size sorting are make-or-break, and raw feed without contacts is worthless to them (this is our Apollo enrichment doing the work OSHAlert does with Google Places phone lookups). Second stall: "is this fresher than the free OSHA site?" — the answer must be *open-inspection tracking* (before penalties post), which OSHAlert claims and validates as the freshness bar.

**Q6 — Future-fit:** More agencies publish machine-readable enforcement every year; AI-spam saturation keeps raising the premium on verifiable-event outreach; and each subscriber's outcome data (which citation types convert to engagements) compounds into a scoring moat no scraper can copy. **Named risk:** OSHA news-release volume varies by administration; the raw enforcement dataset — our actual source — has stayed published, but coverage breadth should be watched, and EPA/FMCSA diversification is the hedge.

### Narrowest-bet statement
> By **2026-08-16**, put **a real 7-day Texas OSHA citation digest with enriched decision-maker contacts** in front of **a safety-consulting firm owner sourced from the ASSP directory or the 130K-member EHS LinkedIn group** to test whether they'll pay **$99/mo** for **a weekly cited-employer lead feed**. If no paying signal by **2026-08-23**, the wedge is wrong.

All four pressure points pass: demo-able tomorrow (ingestion runs today; digest is a formatting job), one thing it does (fresh cited-employer leads with contacts), one named buyer class reachable tonight via communities already mapped, and a falsifiable 7-day read. This also honors the one validated learning from the content project: **delivered artifacts beat explanations** — we lead with their state's actual digest, not a pitch.

---

## Benchmark deep-dive: OSHAlert

**Stress test:** Profitable? — unknown (no traction markers; likely pre-revenue: treat as a *market test*, not a proven business). Understandable? ✓ (poll DOL data → enrich phone → digest + dashboard → subscription). Executable? ✓ (we already run 60% of the pipeline). Revenue-focused? ✓ (their pricing page is our anchor). Three of four hard-pass; the profitability unknown cuts both ways — the price point is validated as *chargeable*, not yet as *retainable*.

| Dimension | OSHAlert | Ours | Gap/verdict |
|---|---|---|---|
| Price | $49/$149/$399/mo by state count | $99/$299/$499 by state × agency | Price above, justify with coverage |
| Coverage | OSHA only | OSHA + EPA ECHO + FMCSA interventions | **The wedge** — nobody has 2 of 3, let alone 3 |
| Freshness | Nightly; tracks open inspections pre-penalty | Must match open-inspection tracking to compete | Their real innovation; do not skip |
| Enrichment | Google Places phone numbers | Apollo person-level contacts + hiring signals | Deeper; person > switchboard |
| Delivery | Digest + dashboard + pipeline tracker | Digest first; **plus an approval-queue send pipeline they don't have** | We're the only feed that can also *send* |
| Distribution | None visible | Free lookup tool (Idea 2) + per-company pages + communities in `monitoring-sources.md` | Their weakness; our mapped ground |

**Blue-Ocean grid:** *Eliminate* — lead databases, warmup, dashboards-first (digest is the product). *Reduce* — UI surface, signal breadth (enforcement + hiring only; no funding/tech-stack noise). *Raise* — coverage (3 agencies), enrichment depth, freshness. *Create* — the enforcement-feed-to-outreach pipeline (feed → grounded draft → human approval → send → outcome tracking), and the free-lookup distribution engine that no data vendor in this niche has.

---

## One-page strategy brief

- **Problem:** Sellers-to-cited-employers (consultants, trainers, brokers, EHS vendors) find out too late, from raw government sites, with no contacts attached.
- **Solution:** A weekly enforcement lead feed — OSHA now, EPA/FMCSA next — enriched to a named decision-maker, optionally flowing straight into a human-approved outreach pipeline.
- **Audience:** Principals of small US safety-consulting/training firms (~51K firms); second ring: insurance loss-control, PEOs, EHS software vendors.
- **Channels:** (1) The free safety-record lookup + per-company pages — SEO/GEO surface that self-selects exactly these buyers; (2) the EHS LinkedIn groups/associations already mapped (130K+, 83K, NAEM, ASSP) via delivered-artifact DMs. Expected CAC ≈ $0 cash, founder time only.
- **Revenue model:** $99/$299/$499/mo subscriptions; Knowella as customer zero proves the feed on our own pipeline metrics.
- **30 days:** Wk 1 — sample digest + 10 delivered-artifact conversations + Stripe link. Wk 2 — verdict on the bet; if alive, digest automation + state filters. Wk 3 — free lookup tool live on knowella.com (GEO asset + intake). Wk 4 — ECHO bulk import (the deferred day of work), first paid cohort, decide FMCSA phase.

**And the existing outreach app?** It becomes the delivery layer, not the product. Its next campaign should be fed by (in order): the hiring signal that's already built and switched off (~5,507 in-ICP people at companies hiring safety roles — still step zero from `prospect-signals-research.md`), then feed items, then lookup-tool visitors.

---

## What this research rules out

- **GEO dashboards** — funded knife-fight, $20/mo floor, measuring a black box.
- **Warm-intro software** — $66M incumbent died; constraint is human, not software.
- **LinkedIn-engagement capture products** — served (Trigify et al.), ToS-fragile, wrapper adds nothing.
- **Lead databases / warmup / volume tooling** — re-confirmed dead ends from the July market research.
- **Generic interactive-magnet builder** — survivors are fine but distribution-bound; the *vertical instance* (Idea 2) is worth building, the *builder* is not.

## Build notes for the feed (verified 2026-08-15, from the ergonomics research)

These answer "how would we actually ingest this" and were confirmed against the live DOL API and OSHA's own tools:

- **The real-time path is the DOL API, not scraping.** `apiprod.dol.gov/v4/get/OSHA/violation/json` (free key, `X-API-KEY` header) exposes the `violation` table (dataset 10338) with a `standard` column, refreshed **daily**. Join to `inspection` (10334) on `activity_nr` for `estab_name`, `naics_code`, `site_state`, `open_date`. The IMIS establishment search lags ~2 days; the aggregate Industry Profile tool is fiscal-year-locked and 4–15 months stale.
- **General-duty citations publish their narrative text.** `violation_gen_duty_std` (dataset 10340) carries `line_text` per citation, daily. This is what lets a feed say *why* someone was cited — ergonomics vs heat vs workplace violence — rather than just that they were.
- **Standards are stored punctuation-stripped and zero-padded**: `1910.178` → `19100178`. The General Duty Clause is its own literal code, `5A0001`.
- ⚠️ **State plans do not use federal codes.** Minnesota cites `182.653(02)`; a `5A0001` filter is silently federal-only and drops all 22 state-plan states. FY2025 state-plan `5A0001` totals just 64 citations, nearly all California.
- **Citations appear on issuance, and OSHA has up to 6 months post-inspection to issue** — so any new-citation feed inherently trails the inspection by weeks to months. This is the freshness ceiling, and it's why OSHAlert's open-inspection tracking (before penalties post) is the real competitive bar.
- ⚠️ **No working public bulk download of the violation table exists any more** — `enfxfr.dol.gov` and `enforcedata.dol.gov` now redirect to a React SPA, and data.gov's CKAN API returns Not Found. The API is the only route.

## Open questions (first-party tests, not more research)

1. Will a safety consultant pay $99/mo? (The narrowest bet — answers itself in 7 days.)
2. Does citation-triggered outreach beat 0.21% for Knowella's own pipeline? (Sources page already measures it.)
3. What share of OSHA-cited employers can Apollo actually enrich to a named safety/ops contact? (Determines feed quality; measurable today on last week's citations.)
4. Does OSHAlert have customers? (Watch for testimonials/case studies appearing; if they hit traction first, speed matters more.)

## Source quality notes

Funding rounds, OSHAlert/Shovels/GovSpend pricing, Pew click data, G2 buyer-survey, and the Google/Yahoo sender rules are primary or journalistic — high confidence. All conversion multipliers (2.4x interactive, 8–10x warm, 15–25% signal replies, 4.4x AI-referred) come from parties selling the corresponding category — direction yes, magnitude no. IBISWorld firm counts are single-source. The DerivateX citation study is single-source and recent; its "G2 gets zero citations" finding is load-bearing for Idea 2 and worth a spot check before investing heavily.
