# Getting clients for the ergonomics product — discovery research

*Researched 2026-08-15 · four parallel web scans (buyer pipeline, competitive landscape, regulatory triggers, discovery channels) + one nested validation-literature review · primary-source verification of the key statistic done by hand.*

**The question:** we have `ai_ergo` — phone video in, pose estimation out, scored against REBA, RULA, NIOSH lifting equation, Snook/Liberty Mutual tables, HSE MAC and WISHA, returning an annotated video plus per-joint angle timelines. Backend/API only, no marketing site, no case studies, no named customers. How do we get clients for it?

---

## The headline, before anything else

**Do not build another end-user ergonomics app. Sell the scoring engine to the people who already own the accounts.**

Three findings drive that, each verified independently:

1. **The application layer is crowded and enterprise-gated.** At least nine vendors ship computer-vision ergonomic scoring today, several with Fortune 500 references and real money behind them. It is a 100% enterprise-sales category — every single vendor gates pricing behind a demo, and there is no self-serve motion anywhere.
2. **The API layer is verifiably empty.** No ergonomic-scoring API exists anywhere. `docs.tumeke.io` does not resolve; VelocityEHS has no developer portal (`developer.ehs.com` is NXDOMAIN); the one real independent pose API (wrnch) was acquired by Hinge Health in Sept 2021 and closed; QuickPose ships joint angles and explicitly stops at *"REBA and RULA-**style** scoring."* SafetyCulture/Mitti runs an open marketplace with self-serve API tokens and ~35 listings — **zero in ergonomics, computer vision, MSK or posture.**
3. **The services layer has the accounts and no engine.** Briotix, WorkWell, ATI Worksite Solutions, Fit For Work and Work-Fit staff certified ergonomists onsite and bill **$150–225/hour, $1,200–1,800/day, $250–450 per assessment with written report.** Fit For Work markets a proprietary reporting layer and names no AI or CV tool anywhere. They are customers and resellers, not competitors.

`ai_ergo` being backend-and-API-only — which reads like an unfinished product — is accidentally the only genuinely differentiated asset we have.

---

## The validation question, verified by hand

I found three conflicting readings of the same paper across the scans (κ = 0.41, κ = 0.57 weighted, κ = 0.15–0.25), so I fetched the primary source. **The skeptical reading was correct.**

**Balogh, Cui, Mayer, Koehncke, Dueck & Lang, *PLoS One* 20(5):e0323262, 9 May 2025** — 21 videos, three human raters (2 / 10 / 15+ years), each rating three times, plus TuMeke Risk Suite. No vendor funding, no competing interests. [PMC12063896](https://pmc.ncbi.nlm.nih.gov/articles/PMC12063896/)

**Humans agree with each other poorly:**

| Measure | ICC (95% CI) |
|---|---|
| Inter-rater, final REBA score | **0.36 (0.21–0.52)** |
| Inter-rater, final risk level | **0.22 (0.07–0.38)** |

**Repeatability — the AI's structural advantage:**

| Rater | Final REBA score | Final risk level |
|---|---|---|
| Novice | 0.51 | 0.38 |
| Intermediate | 0.66 | 0.63 |
| Expert | 0.89 | 0.73 |
| **TuMeke** | **1.00** | **1.00** |

**Agreement with humans on the final score is poor (κ, self-selected timepoints):** novice 0.20, intermediate 0.15, **expert 0.25**.

**But the per-region picture is where the product design lives.** At self-selected timepoints, neck comes out *negative* (−0.44 intermediate, −0.27 expert), lower arm and wrist ≈ 0. **At AI-selected timepoints, trunk jumps to 0.63–0.68 and legs to 0.57–0.65**, upper arm reaching 0.53 for the expert — while neck, lower arm and wrist stay junk.

Authors' own words: the tool *"may be useful for individuals with less practical experience… in increasing the reliability of their assessments"* and *"may be used with most confidence when the trunk, legs, and upper arm are of greatest interest."* They measured reliability and agreement — **"validity was not"** assessed.

### What this means for our code, concretely

`knowella-ml` runs MediaPipe PoseLandmarker (per `accuracy_log.md`). A 2025 *Sensors* study (Sprague et al., n=11) measured MediaPipe hand/wrist joint angles at **22.5° RMSE, r = 0.45** against Vicon — not a measurement, a guess. Both REBA and RULA score the wrist. Our own log already shows the same failure family: left-side landmarks null when the worker turns sideways (Run 2, t=11s), all landmarks lost at t=17s, and smoothing papering over both.

**So the defensible design — which no competitor ships — is:**
- Score and stand behind **trunk, legs, upper arm**.
- **Flag neck, lower arm and wrist for human verification, in the product**, with per-joint confidence.
- Treat **AI timepoint selection as a headline feature**, not plumbing: the paper shows it lifts agreement substantially, including between humans.
- **Ask the user for force/load and coupling** — a camera cannot see them, and force is the objection every credentialed ergonomist raises first.

---

## Scan digests

### Buyer pipeline — who actually pays

- **The insurer channel is largely closed at the top.** **Travelers has offered AI-based ergonomic assessment from smartphone video — scoring posture, motion, force and repetition — free to policyholders since September 2020**, wrapped in their EJIP process with a nationwide staff of certified ergonomists ([investor release](https://investor.travelers.com/newsroom/press-releases/news-details/2020/Travelers-Introduces-AI-Based-Ergonomic-Assessments/default.aspx)). Liberty Mutual owns the Snook science outright and publishes the tables free. Do not pitch these as customers.
- **But loss control is rationed by premium, and that gap is the opening.** NIOSH-authored peer-reviewed study of nine WC insurers (*J Safety Research*, 2018): **eight of nine already provide ergonomics assistance**, but *"larger accounts received two to three visits yearly; smaller ones received none or one visit every two-to-three years."* Small and mid-market employers are structurally starved of assessment by their own carriers. An API is capacity.
- **The realistic insurer entry points are TPAs, MGAs and regional carriers**, not the top five. Sedgwick's loss-prevention line names ergonomic services explicitly and lists insurance carriers among its clients. CompScience holds an MGA agreement with Nationwide underwriting and Swiss Re reinsuring ($27.6M Series B, Feb 2025). Insurer vendor marketplaces exist (EMC publishes one) — though **how a vendor qualifies is not published anywhere**, which is the main unknown.
- **⚠️ Kill the premium-credit pitch.** No US premium credit, filed rate deviation, or dividend program was found anywhere that triggers on ergonomic assessment or ergonomics software. Credits attach to *program types* — return-to-work, drug-free workplace, certified safety programs. NY Code Rule 60 qualifies only those three.
- **MSD economics for the business case:** 2025 Liberty Mutual Workplace Safety Index — overexertion from outside sources **$13.7B**, other exertions **$3.9B**, repetitive motion **$1.8B**, against $58.78B for all disabling injuries. **MSD-attributable ≈ 33%.** Overexertion has ranked #1 in all 25 editions.
- **⚠️ Be careful with ROI claims.** The systematic review (Sultan-Taïeb et al., *BMC Public Health*, 2017; 9 studies) found lifting-equipment payback of **3–5 years** from the employer's perspective and rated evidence "limited for all four intervention types." Case-study sources claiming under one year are selection-biased. A CFO who checks will find the 3–5 year number.
- **The regulatory template worth citing in warehousing pitches:** the December 2024 DOL/OSHA settlement with Amazon requires a corporate-wide ergonomics program, **annual ergonomic risk assessments**, and a **designated Site Ergonomics Lead at each location**, with biannual injury-trend review. That is a per-site, per-year recurring measurement obligation — the exact shape of an API subscription.
- **⚠️ Don't plan to enter through public procurement.** No public RFP anywhere was found specifying AI/CV ergonomic scoring. Alameda County's ergonomic *assessment services* contract went to **Humanscale — a furniture manufacturer**. In office ergonomics, assessment is a loss-leader attached to product sales.

### Competitive landscape

| Vendor | Approach | Methods automated | Pricing | Validation | Traction |
|---|---|---|---|---|---|
| **TuMeke** | Phone video | REBA, RULA, NIOSH | Contact sales; 14-day trial | Independent PLOS One study it didn't commission and doesn't cite | $10M Series A (Intel Capital, Dec 2023); Siemens, Cargill, New Balance, Hitachi Astemo |
| **VelocityEHS** (Humantech + Kinetica) | Video → 3D mocap | Proprietary MSD scoring; REBA/RULA *not* marketed | Platform ~$20/user/mo (3rd-party); **3D SSPP $2,500 perpetual** — the only published price in the category | **Yes** — co-authored *Ergonomics* 2026 paper, 6.7M-frame dataset, 2.4° mean angle error (vs own ground truth, no human-score agreement reported) | ~$70.5M revenue, 13,000+ customers |
| **Retrocausal** | Video | **REBA, RULA, OWAS, NIOSH, Snook, LM-MMH, hand strain, pinch force** — widest coverage found | Not published | None | 3M across 15 plants |
| **Inseer** | Video, "sensorless AI" | Not specified | Not published | None | Hyundai Metaplant America |
| **Intenseye** | Continuous CCTV | REBA, RULA | Not published | None | $64M Series B (Lightspeed, Feb 2024); Unilever, Siemens, Heineken |
| **Soter** | **Pivoted wearable → phone video** | RULA, REBA, NIOSH | Wearable $399/device | None | $12M Series A Apr 2022, nothing since |
| **3motionAI** | Video | ROSA, workplace risk | Not published | None | Benchmark Gensuite minority investment Jan 2025; **possible Oct 2025 insolvency — UNVERIFIED, site still live** |

Also in-field: viAct, Voxel and Protex AI (the latter two flag bends but do not score REBA/RULA).

**Structural reads:**
- **Vision is beating wearables, and the tell is directional migration**: Soter, Modjoul and dorsaVi have all added cameras; no camera vendor has added wearables. dorsaVi's revenue fell A$2.35M (FY22) → A$1.13M (FY25). StrongArm is at 21 employees against a $200M 2022 valuation. Kinetic gave up selling devices and became a Nationwide-backed workers'-comp MGU.
- **The suites build, they don't buy.** Only VelocityEHS has ever acquired an ergonomics vendor (Humantech 2018, Kinetica 2021). **Zero acquisitions of a CV-ergonomics vendor by any EHS suite since July 2021.** The one embed-a-third-party bet (Benchmark → 3motionAI) may have ended in that partner's insolvency.
- **Method breadth is contestable ground.** Nobody automates **HSE MAC** (free under UK Open Government Licence v3.0, explicitly reusable commercially) or **WISHA**. Retrocausal already ships wider coverage than us on the rest.
- **⚠️ IP note:** REBA/RULA are journal-published instruments; NIOSH's equation is US public domain; HSE MAC is OGL. Implement from the papers with citation; don't copy Liberty Mutual's tables, UI or branding. Their terms-of-use page returned 403 and needs a real legal read.

### The demand-side risk, stated plainly

This is the finding most likely to kill the business quietly, and it deserves to be on the first page of any plan:

- **Roberts et al., *IJERPH* 2023** — systematic review of 18 articles on whether MSD risk-factor screening tools reduce injury: **no high-quality studies**, inconsistent effectiveness. Verbatim: *"There is limited evidence regarding use of MSI risk factor screening tools for preventing injury."*
- **Iyer et al., *Ergonomics* 2025** — scoping review, 84 studies: *"no epidemiological studies to date have confirmed a direct impact on reducing MSD rates."*
- **Kee, *IJERPH* 2022** — the reliability ranking is OWAS > RULA > REBA, but **RULA correlates best with actual MSDs while OWAS's action category showed no significant association (p > 0.10)**. The most reliable tool is the least valid one. Inter-method agreement: RULA–REBA 53.8%, OWAS–RULA 28.1%.
- **Agostinelli et al., *Scientific Reports*, Nov 2024** — CV tools against four expert ergonomists on three real production lines: risk-*level* accuracy 40–80%, **exact-*score* accuracy 9.09–60%**. Documented causes: lighting glare, racks occluding rear views, adjacent workers, arms disappearing into boxes.
- **Carrie Taylor, M.Sc., CCPE, CPE** ([OHS Canada, 6 Apr 2026](https://www.ohscanada.com/opinions/the-questions-everyone-should-be-asking-about-ergonomics-ai-tools/)) — the credentialed critique: force cannot be measured from video and is arguably the strongest injury predictor; 2D misses lateral/twisting motion (she reports a sideways-pushing task rated low risk by AI while biomechanical analysis exceeded thresholds); gloves and sleeves make wrists uninterpretable; automating a 1990s *screening* tool adds *"speed, but not accuracy."* She reports from ACE 2025 that **AI scores did not correlate with incident data while measured force and duty cycle did** (underlying paper not independently located).
- **There is no accuracy standard, no accreditation body, and no regulator checking** — BCPE certifies people, not software. A vendor can ship any accuracy whatsoever and be fully compliant.

**Implication:** sell **repeatability, speed and coverage** — all defensible — and never sell **injury prediction**, which the literature does not support for anyone.

### Discovery channels

- **The free-tool vacuum is real and verified.** There is no ungated, no-signup, English-language "upload a video → get a REBA score" tool anywhere on the open web. The free layer is Excel spreadsheets (NC State's 10 calculators, Cornell CUergo's `.xls` macros), PDFs, and the official CDC/NIOSH NLE Calc app at **2.8 stars**. Ergonautas/Ergoniza (Universitat Politècnica de València) is the only free AI posture tool and it requires an account and paywalls export. The best open-source REBA implementation has 21 stars and has been dormant since Nov 2021.
- **Every commercial vendor is demo-gated — which means AI assistants cannot see, use, or cite any of their capability.** Combined with the earlier finding that ChatGPT cites niche independent content ~82% of the time and G2/Capterra ~never (and **Capterra has no ergonomics category at all**), an ungated tool page is the only citable artifact available in this category.
- **The commercial-intent query is currently answered by fabricated content.** "Best ergonomic assessment software 2026" returns AI content farms whose top-10 lists include board-management software and a web-design agency, with zero overlap between them and no mention of TuMeke, Retrocausal or Inseer. Nobody real is answering the question.
- **The field has no watering hole *for credentialed ergonomists*** — no Slack, no Discord, no surviving forum, and Ergoweb last published in February 2022 (its site search returns nothing on AI or computer vision at all). But the practitioners who *buy* this software do gather: **r/SafetyProfessionals and r/EHSProfessionals**, not r/ergonomics, which is consumer desk-setup content. Plus the ASSP Ergonomics Practice Specialty community and conferences.

### Practitioner sentiment — the gap is now closed, and it inverts one assumption

An earlier caveat in this file said no practitioner sentiment was obtainable. It since was, via Reddit archive APIs with verifiable comment IDs. Three findings matter:

**1. The buyer is usually not an ergonomist — and that reframes the whole pitch.** Every positive review frames the value as covering an *absence* of expertise, not matching an expert:

> *"We had an intern trial it, and they cranked out a ton of assessments pretty quickly **which was great since we don't have much ergo expertise on site**."* — r/SafetyProfessionals, Sept 2024, on TuMeke
> *"The video capture is cool if you have **alot of sites with no hse support**."* — r/SafetyProfessionals, Jan 2024, on VelocityEHS/Humantech

This lines up exactly with the Balogh finding that the tool helps *less experienced* users most. It also means the "certified ergonomists will resist us" risk is smaller than the credentialed critiques suggest — **the CPEs aren't the buyers; the safety managers with no CPE on site are.** Both segments are real: sell the API to the services firms that *have* ergonomists, and the tool to the sites that don't.

**2. The skepticism is latent, not expressed — nobody is auditing the output.** The direct question *"Are the AI tools fairly accurate?"* (r/SafetyProfessionals, Nov 2024) **received no answer**. Another buyer asked whether it replaces or merely assists an ergonomist; also unanswered. No practitioner anywhere in the archive named occlusion, 2D ambiguity, coupling, or the which-frame problem — those critiques exist **only** in the peer-reviewed literature. So a credible validation story is a *differentiator*, not a defence.

**3. Practitioners' own critique is that posture scores are the wrong object, and the market leader agrees.**

> *"REBA is way over focused on posture and ends up telling you nothing. […] Force > repetition > posture"* — r/EHSProfessionals, July 2023
> *"use REBA calculations as more of a way to determine a general risk score, but ultimately that number does not mean a whole lot in the grand scheme."* — 14-year EHS practitioner, July 2023

VelocityEHS publishes the same argument ("Why You Need More Than Just RULA and REBA," Feb 2024): the methods rest on 1980s research and *"assessment of industrial tasks (and forceful exertions) are over-simplified and under-measured."* **A product that outputs only a REBA number is arguing on ground the field has already conceded is weak.**

**Confirmation for our design rec:** the Balogh paper documents that TuMeke's force, load and coupling scores were *"manually selected by the researcher."* Peer-reviewed proof that the market leader's camera does not see force either — so asking the user for it is the category norm, not our weakness.

⚠️ **Reputation note:** the researcher screening for vendor astroturf in these threads flagged **two near-identical Knowella plugs posted in December 2025** as transparent promotion, alongside BalanceFlo, viAct and CompliEase (one such comment was removed by moderators). If that was us or an agency acting for us, it is worth knowing that it reads as astroturf to exactly the audience we want, in the two subreddits that matter most.
- **The trade show consolidated.** `ergoexpo.com` now redirects to nationalergo.org, which lists nothing after Nov 2025 and moved virtual. **IISE Applied Ergonomics Conference is the last in-person centre of gravity** — and TuMeke, Retrocausal, Inseer, Kinebot, VelocityEHS, BCPE, NC State and U. Michigan all exhibit there.

### Regulatory landscape — where the law bites, and where it doesn't

**There is no US federal ergonomics standard, and the federal trend is retreat, not advance.** The 2000 Ergonomics Program Standard was killed by Congress under the Congressional Review Act (Pub. L. 107-5, March 2001), which bars OSHA from reissuing anything substantially similar without new legislation. Enforcement runs solely through General Duty Clause §5(a)(1). The guidelines are explicitly *"advisory, do not create new employer obligations, and are not basis for citations,"* and **name no method**. In **July 2025 OSHA withdrew** the rulemaking that would have added an MSD column to the 300 Log (90 FR 28257), and separately **proposed narrowing the General Duty Clause** (FR 2025-12236, still proposed, comments closed Sept 2025).

**The federal enforcement channel is far too thin to build a pipeline on — now quantified precisely.** GDC citations carry standard code `5A0001`. Federal totals run **600–900 a year, centring near 700** (FY2025: 694 citations / 666 inspections / $5.93M, reproduced two independent ways). But that covers heat, workplace violence and combustible dust too, and the FY2025 NAICS distribution is heat-dominated — landscaping alone is 55 citations, versus 30 for general warehousing. **Ergonomics-plausible industries cap at 61 citations (8.8%), and the best-supported estimate for actual ergonomic GDC citations is 15–35 a year.** For scale: OSHA's largest ergonomics enforcement campaign in a decade — the Amazon action — produced **7 citations across 6 sites**, and **four of those were vacated outright** (New Windsor, Deltona, Aurora, Nampa all now show $0), one settled at $145,000, one remains contested. Healthcare GDC enforcement has all but stopped: 6 citations in FY2025, of which zero were nursing homes. **No federal ergonomic GDC citation has been announced in 2025 or 2026.**

**Two things that matter if we ever build a feed on this:**

- **The narrative text is published.** `OSHA_violation_gen_duty_std` (DOL dataset 10340) carries the actual `line_text` of every general-duty citation, refreshed **daily**, joinable on `activity_nr` + `citation_id`. That is the only way to separate ergonomic citations from heat and violence — keyword-match "musculoskeletal," "ergonomic," "repetitive," "lifting." Needs a free DOL API key.
- **State plans do not use `5A0001`.** They cite their own statutes — Minnesota uses `182.653(02)`. Any query filtering on `5A0001` is silently federal-only. Also note standards are stored punctuation-stripped (`1910.178` → `19100178`).

⚠️ **The live ergonomics enforcement front is Minnesota, not the GDC — and this contradicts the "untested statute" assumption.** MN OSHA issued **26 citations across 10 inspections under Minn. Stat. §182.677 in FY2025** (~$80,000): grocery wholesale 10, nursing homes 7, hospitals 6, meat processing 2, warehousing 1. Meanwhile **Cal/OSHA issued zero §5110 citations in FY2025** across 15 high-MSD industries, confirming that standard is a dead letter in practice.

**The cited companies are named and public** — no data-practices request needed:

| Company | §182.677 action |
|---|---|
| Bix Produce | inspection opened April 2024 |
| Performance Food Group | inspection opened April 2024 |
| Sysco Minnesota | cited 2024-10-08 |
| US Foods | cited 2024-11-18 |
| Amazon MSP6 Lakeville | cited 2025-09-18 |
| Amazon MSP1 Shakopee | cited 2025-10-16 |
| McLane | inspection opened 2026-04-15 |

**They concentrate in NAICS 424410 — grocery and foodservice wholesalers, not warehousing giants.** That is a sharper vertical than "warehousing," and it is where the first ergonomics outreach should point.

⚠️ **Correction to an earlier claim in this file's source material:** the April 2024 MNOSHA citation against Amazon Shakopee was **not** an ergonomics citation. Inspection 1707152.015 (opened 2023-10-23, cited 2024-04-23, $10,500, contested the next day) cited **Minn. Stat. §182.6526(2)** — the warehouse *quota* law — and **§182.653(02)**, the state general-duty clause. Amazon's actual §182.677 ergonomics citations came later, in September and October 2025.

⚠️ **Two corrections to what I said earlier in this conversation:**

- **The Warehousing NEP was reissued two weeks ago and the ergonomics mandate was removed.** CPL-03-00-026, signed 6 July 2026, effective 31 July 2026, superseding the 2023 version. Its own "Significant Changes" list states: *"Removed mandatory screening requirements for ergonomic and heat hazards"* and *"Extended the NEP expiration date to five years."* So the program runs to **2031** (more warehouse inspections) but ergonomic screening went from **mandatory to discretionary**. Site selection is random within NAICS, so it produces no targetable list either way.
- **Amazon's ergonomic citations were withdrawn, not upheld.** OSHA withdrew nine of the ten in the December 2024 settlement; Amazon accepted only one unrelated citation. **The GDC-ergonomics theory has never been litigated to judgment** (the controlling precedent, *Pepperidge Farm* 1997, held GDC *can* reach lifting hazards but vacated all 175 violations for failure to prove feasible abatement). Sell the settlement's **abatement obligations** — corporate ergonomics team, annual risk assessments, Site Ergonomics Lead per facility — as the market signal. Never frame it as a legal defeat for Amazon.

**Where the law does bite is state-level, and it bites on human competence, not on tools:**

| Jurisdiction | Instrument | Status | What it requires |
|---|---|---|---|
| **New York** | Labor Law **§789**, Warehouse Worker Injury Reduction Program (Ch. 652 of 2024; NYSDOL guidance P327) | **In force since 1 June 2025** | Applies at **100+ employees at a single warehouse distribution center, or 1,000+ statewide** (NAICS 493 exc. 493130, 423, 424, 45411, 49211). Written worksite evaluation **by a "competent person"** — ergonomist, industrial hygienist, CSP or other H&S professional — assessing rapid pace, forceful exertions, extreme/static postures, repetitive motion, contact stress, vibration, cold; **each job, process, shift and operation**; worker input mandatory; **reviewed and updated annually**; new/changed jobs analysed **within 30 days**. A safety committee may demand review by a **board-certified ergonomist**, due within 30 days. Penalties assessed **per day**, plus a private right of action. |
| **Minnesota** | Stat. **§182.677** | **In force** (believed 2024-01-01, ⚠️ exact date unverified) | Written ergonomics program for health-care facilities (no headcount floor), warehouse DCs 100+, meatpacking 100+; MSD risk-factor assessment, training, early reporting, **annual evaluations** and reassessment on process change. |
| **California** | 8 CCR **§5110** | In force since 1997 — the only US ergonomics standard | Reactive: **2+ physician-diagnosed RMIs** in 12 months, same identical work activity, ≥50% work-caused. Small-employer exemption repealed in 2000, so no headcount floor. ⚠️ **But enforcement is near zero** — §5110 appears in no top-cited list for warehousing, poultry, supermarkets or nursing homes. A compliance-risk argument, not a lead source. |
| **Washington** | **RCW 49.17.520** (ESSB 5217, Ch. 112, Laws of **2023**) | **Authority restored; rules imminent** | Resolves the conflict I flagged earlier — both scans were half-right. The old rule was repealed by Initiative 841 in 2003; the 2023 law restored limited rulemaking authority. L&I may regulate industries whose MSD claim rate exceeds **2× the statewide rate**, one per year, and **no rule may take effect before 1 July 2026**. CR-101 filed Oct 2024 for **airline ground crew** (Risk Class 6802); **fulfillment centers (Risk Class 2103)** announced Nov 2024, rulemaking not yet started. 27 high-priority classes published 30 Nov 2025. |

**None of these names a tool, a method, an angle, or an accuracy threshold.** New York's entire quality gate is a *human credential* — and BCPE, which issues it, **certifies people only and offers no product certification of any kind.**

⚠️ **Do not assume the New York mandate is spreading — it isn't.** A sweep of Connecticut, Massachusetts, Rhode Island, Virginia, Michigan, Colorado, Maryland and California for 2025–26 found **zero ergonomics or MSD-program bills anywhere**. What is spreading is the California AB 701 *quota-transparency* model: Connecticut enacted it in March 2026 (PA 26-1, effective July 2026) and Rhode Island in June 2026 (effective January 2027), while Massachusetts and Virginia versions died. None of them requires an ergonomic evaluation, an ergonomist, or an injury-reduction program. Maryland and Colorado have nothing at all — California's own 2025-26 session returns a verified **zero hits for "ergonomic."** So NY §789 is a one-state mandate, not the leading edge of a wave; size the opportunity accordingly, and don't build a pitch around inevitable regulatory tailwind.

**Healthcare is the one mandate-rich vertical, with a caveat that probably disqualifies it.** Nine states have enforceable safe-patient-handling statutes — Washington, California, New York, New Jersey, Minnesota, Texas, Rhode Island, Illinois and Maryland — most requiring hazard assessment, annual training and annual program evaluation, several covering nursing homes as well as hospitals, and Minnesota's binding *every licensed health care facility* in the state. That lines up with where Minnesota's ergonomics enforcement actually landed: **7 nursing homes and 6 hospitals** of its 26 FY2025 citations. (Two corrections to the list that circulates online: Ohio's law was a voluntary interest-free equipment-loan program and was **repealed in 2015**, and Missouri has no such statute at all — the section usually cited is palliative-care definitions.)

⚠️ **But the interventions here are ceiling lifts, lift teams and equipment, not posture scores — and you cannot casually film a patient.** Video assessment in patient-care areas carries consent and privacy problems that simply don't exist in a warehouse aisle. Treat healthcare as a mandate-rich vertical we are *not* well-positioned for, unless someone solves filming staff-only handling drills rather than live care.

Three things to watch rather than act on: the **1.5× BLS injury-rate investigation trigger** keeps recurring in these bills (it was in Massachusetts' and in Connecticut's governor's bill, and was stripped from Connecticut's enacted version) and is the natural bridge from quota law to injury law; **Virginia HB 1451 was continued**, so it carries into 2027 with a substitute already drafted; and **Michigan HB 4435** would repeal the statute that currently *forbids* MIOSHA from writing any ergonomics rule — stalled in committee, but it is the single most consequential ergonomics bill in the country if it ever moves.

**Two strategic consequences:**

1. **"Equip the competent person" is not just good positioning — it is the shape the law itself takes.** NY demands an annual written evaluation by a named competent human, escalating to a board-certified ergonomist on dispute. Software cannot be the accountable entity; it can only make that person faster and more consistent. That is precisely the product we should build.
2. **There is no accuracy floor anywhere on earth.** ISO 11226 clause 3.3 — the only standard addressing *how* posture is measured — explicitly delegates accuracy to the evaluator and states that *"in most cases, direct observation (without measuring systems/devices) will do."* No standard sets a joint-angle tolerance, requires tool validation, or requires inter-rater reliability. No accreditation body exists. **Which means every "±X° accurate" claim in this market is unfalsifiable marketing, and a published, independently-testable accuracy methodology would be category-defining rather than a compliance checkbox.**

⚠️ **One regulatory trap to avoid deliberately.** Ergonomic assessment software sits outside FDA device regulation (21 U.S.C. §360j(o)) and outside EU MDR (MDCG 2019-11: software needs a medical purpose *on its own* to qualify) — **as long as we assess a job, not a patient.** MSDs like carpal tunnel and tendinitis *are* diseases. A vendor marketing individual-worker MSD *prediction* or *injury prevention for a named person* argues itself into device regulation with clinical-evidence obligations attached. Keep every claim at job/task level. This is also worth checking in competitors' copy — it is unremediated exposure, not a feature.

### The targeting signal — verified, and it connects to the enforcement-feed work

**OSHA publishes per-case injury narratives tied to named establishments, free and in bulk.** The live CSV header was read directly from [OSHA's Establishment-Specific Injury and Illness Data](https://www.osha.gov/Establishment-Specific-Injury-and-Illness-Data) page — these are verified column names, not a description of them:

```
establishment_name, ein, company_name, street_address, city, state, zip_code,
naics_code, industry_description, annual_average_employees, total_hours_worked,
job_description, SOC_code, SOC_Description, date_of_incident, incident_outcome,
dafw_num_away, djtr_num_tr, type_of_incident,
New_nar_before_incident, New_nar_what_happened, New_nar_injury_illness, New_nar_object_substance
```

Files: `ITA_Case_Detail_Data_2023_through_12-31-2023OIICS.zip` (OIICS-coded — structured nature-of-injury and event codes), `ITA_Case_Detail_Data_2024_through_12-31-2025.zip`, `ITA_Case_Detail_Data_2025_through_3-15-2026.csv`, plus 300A summary files from CY2016 onward.

So for each individual injury case, at a **named establishment with street address and EIN**, we get the free-text injury description (`New_nar_injury_illness` — "lumbar strain," "rotator cuff," "carpal tunnel"), what the worker was doing when it happened (`New_nar_before_incident`, `New_nar_what_happened` — "lifting a tote from the bottom rack"), the **job title** and SOC occupation code, and **days away and days restricted** — i.e. severity and cost per case. The narratives are not scrubbed.

**Classify those narratives into MSD/overexertion and we can rank every large high-hazard US establishment by MSD case count, by lost-day severity, and by the specific job title generating them.** The opener writes itself and is verifiable: *"your Daytona Beach plant logged 14 overexertion cases among machine operators last year, averaging 21 days away."* Free, public, national, company-naming — the same asset class as the enforcement lead feed in `client-acquisition-tool-research.md`, which makes these two directions **one pipeline, not two**.

**This was measured, not estimated.** The 2024 file was downloaded (86 MB zip → 520 MB CSV) and counted directly. Filtering OIICS event codes 71/72/73 (overexertion, repetitive microtasks, bodily position):

| Measured on `ITA_Case_Detail_Data_2024` | |
|---|---|
| Total cases | 688,649 |
| **MSD cases** | **216,487 (31.4%)** |
| **Named companies with ≥1 MSD case** | **16,925** |
| **Named companies with ≥100 MSD cases** | **181** |
| Top body part | Back — 72,701 cases |
| Amazon.com Services LLC | 25,417 MSD cases / 1,338,750 lost + restricted days |
| UPS / FedEx / Costco / Trader Joe's | 9,452 / 6,187 / 4,349 / 2,434 |

**Known defects to engineer around:** 10,589 MSD cases have a blank `company_name`; Walmart splits across "Walmart Inc" and "WalMart Stores East LP" (use `ein` as the resolution key); OIICS codes are ML-predicted with ~18% unassigned; and **the 2025 file has narratives but no OIICS columns**, so 2025 needs text classification rather than code filtering.

**A second, independent cost signal exists — and only in one state.** New Jersey is the only US jurisdiction that publishes **per-employer experience modification rates** free and in bulk. The NJCRIB file was downloaded and parsed: **116,451 named employers** with mod, governing class code, street address and expiration date; **2,220 with a mod above 1.5**; median 0.971. Their web UI even supports "every employer in this county with a mod between 1.5 and 4.0." An EMR above 1.5 is an *underwriter-validated* statement that this employer's claims run well above its class — the closest thing to a qualified-by-cost lead list that exists anywhere. (Caveat: NJCRIB is a statutory rating bureau, not a .gov agency.) Everywhere else, EMR is gated — NCCI sells it at $6–24 and only to the carrier of record; WCIRB, PCRB and MWCIA all require authorization; and "experience modification" appears **zero times in the entire CFR**.

**Two more free, named-employer registries** worth layering for firmographics: Texas publishes 2.17M WC subscribers **including `state_standard_premium`** — a live proxy for each named employer's comp spend — and Oregon publishes 130,987 active WC employers with NAICS and employee-count ranges.

**The bonus play:** OSHA's own Site-Specific Targeting directive (CPL 02-01-067, effective 20 May 2025) builds its inspection lists from this same public 300A data — elevated DART rates plus establishments at 2× the national average trending upward. **We can reconstruct OSHA's targeting logic and tell an employer they are likely on the list before OSHA knocks.** Alarming, useful, and entirely honest.

⚠️ **One hard compliance line.** California's EAMS workers'-comp case data is **off-limits**: Labor Code §138.7(a) bars any non-party from obtaining individually identifiable information, and the definition explicitly covers information linked to an identifiable *employer*. DWC logs who requested what. Do not build on it.

⚠️ **Still unverified:** refresh cadence, and whether any administrative action pauses publication.

---

## The plan

### Play 0 — Build the MSD target list *(days, and it needs no product changes at all)*

This is the fastest thing on the list and the only one that pays off immediately for Knowella's own pipeline. Download the ITA Case Detail file, filter to MSD events, aggregate by `ein`, and rank by case count and lost days. That yields **16,925 named employers with a measured MSD problem, 181 of them severe**, each with street address, NAICS, the injured worker's occupation, and a lost-day count that converts straight to dollars.

Then layer the qualifiers: New Jersey employers with EMR above 1.5 (2,220 of them, underwriter-validated), Washington's own top MSD risk classes (fulfillment centers at 40.9 per 1,000 FTE — **10× the state average** — and airline ground crew at 45.8), and the New York §789 covered set (100+ at one site or 1,000+ statewide).

The opener is verifiable, specific, and about something that already happened to them — exactly what the cold-email research says is the only thing still working, and the direct antidote to the 0.21% baseline. Every lead lands in a campaign with a `source_id` so the Sources page judges it against that number.

### Play 1 — Ship the ungated free tool *(weeks, highest leverage)*

A public URL, no signup, no email: upload a phone video → REBA/RULA scored **across every frame**, worst frame surfaced with joint-angle overlay, **per-joint confidence shown in the product** with wrist/neck/lower-arm auto-flagged "verify by hand," force and coupling asked of the user explicitly, free PDF out.

It fills a verified vacuum, it is the only thing in the category an AI assistant can cite, it turns our biggest technical weakness into a visible integrity signal, and it generates the validation dataset for Play 3 as a by-product. TuMeke already proved the pattern with an ungated ROI calculator — they just never applied it to the core capability.

### Play 2 — Sell the API to the services layer *(the revenue wedge)*

Target the ergonomics consultancies and onsite industrial-athlete providers: Briotix, WorkWell, ATI Worksite Solutions, Fit For Work, Work-Fit, Atlas Injury Prevention, plus the long tail of independent CPEs. They bill $150–225/hour and $250–450 per assessment, have the accounts and the credentialed staff, and have no scoring engine. Compressing a three-hour assessment to thirty minutes is pure gross margin for them at unchanged price.

Positioning that survives the profession's objections: **lead with the per-joint angle timeline and annotated video; let the CPE own force, cumulative load and judgment.** That directly answers the credentialed critique instead of colliding with it. Second target ring: EHS suites with open marketplaces and no ergonomics listing (Mitti's has self-serve tokens and zero), and EU/UK consultancies where risk assessment is *legally mandatory* and works-council constraints make on-device/API processing a selling point.

### Play 3 — Publish the validation study *(the credibility asset)*

The position is unclaimed: six of nine vendors have nothing, TuMeke's independent study is one it didn't commission and doesn't cite, and VelocityEHS's paper reports angle error against its own dataset with no human-score agreement at all.

Co-author with a university ergonomics centre — **The Ergonomics Center at NC State** or **Dr. Lang's group at U. Saskatchewan**, who already own the protocol. Anchor the claim on **repeatability against the 0.36 human inter-rater ICC**, report failure modes honestly, and publish the per-joint confidence data. An honest study that names its own weaknesses will out-cite a glowing one, and it is exactly what an AI assistant will surface for "is AI ergonomic assessment accurate?"

### Dated items
- **NC State Ergonomics Symposium — 1–2 September 2026, Raleigh.** Two weeks out. The fastest route to the Ergonomics Center for the study conversation.
- **IISE Applied Ergonomics Conference abstract deadline — 5 September.** Three weeks. Submit to the Applied Research track; a podium slot costs a registration ($1,510 non-member early) rather than a booth, and carries more weight with this audience.
- **Ergo Cup** — vendors cannot enter, but customers can, and finalists are named on stage. Get one customer to enter with a Knowella-driven improvement. It's the one endorsement in this field that money cannot buy.

---

## What this rules out

- **Building another end-user ergonomics app** — nine vendors, enterprise sales, Fortune 500 reference logos, three-year head starts, and no brand on our side.
- **Selling to Travelers or Liberty Mutual** — one ships this free since 2020, the other owns the underlying science.
- **Any premium-credit sales story** — no such credit exists in the US.
- **Public procurement** — buyers there purchase people and furniture.
- **Selling injury prediction or "matches a certified ergonomist"** — the literature refutes both, and credentialed practitioners will attack them in the demo.

## Open questions for first-party testing

1. Will a services provider pay for the API, and per what unit — per assessment, per site, or per seat? The category prices entirely dark, which means no external anchor and full latitude.
2. What is our own per-joint agreement against a certified ergonomist on the same 20-video protocol? Runnable now that the protocol is published.
3. Does the wrist/neck problem improve with multi-view or a better backbone? MeTRAbs topped an independent 16-framework benchmark; MediaPipe did not.
4. How do we qualify for an insurer's loss-control vendor marketplace? The mechanism exists (EMC publishes one); the criteria are not public and need a direct conversation with a regional carrier's risk-control head.

## Source quality

The PLOS One statistics were verified by hand against the primary source after three scans reported conflicting figures — a reminder that secondary readings of the same paper drifted badly. Travelers' 2020 release, the Amazon settlement, VelocityEHS's $2,500 price, and the funding rounds are primary or journalistic. The Liberty Mutual Index and NIOSH insurer study are primary. Vendor injury-reduction claims (68%, 91%, 77%) are all unverified marketing. 3motionAI's insolvency is **unconfirmed** — the primary filing 404s and the site is live. Practitioner quotes were recovered verbatim from Reddit archive APIs with comment IDs and are verifiable; **LinkedIn remains unfetchable**, so "no credentialed ergonomist criticising AI on LinkedIn" means *not found under these constraints*, not *does not exist*. Treat any 2025–26 Reddit software recommendation with suspicion — several are vendor astroturf.
