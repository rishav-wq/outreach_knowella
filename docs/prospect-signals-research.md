# Prospect signals — what actually names a company, and what we can get

*Researched 2026-08-08. Every claim below was probed live; where something failed, the
failure is recorded rather than the marketing copy.*

**The question this answers:** cold lists don't convert — 4,422 Apollo leads produced 9
replies and 0 meetings, because nothing had happened to those people. A *signal* is
something that happened, to a named company, recently, that we can honestly mention in
the first line. This is a survey of every one we can actually obtain.

---

## The finding that matters: hiring signals, already built, never used

A company posting for a **Safety Manager** or **EHS Coordinator** is telling you it is
investing in safety *right now*. It has budget, it has a gap it's trying to fill, and the
role usually reports to the person we sell to.

Apollo supports this and `_build_filters` already implements it
(`q_organization_job_titles` + `organization_num_jobs_range`). It has never been switched
on for any campaign. Measured live against the `knowella-safety-ai` ICP:

| Filter | People in ICP |
|---|---|
| No hiring filter (today's campaign) | 17,665 |
| Hiring `Safety Manager` | **3,514** |
| Hiring `EHS Manager / Coordinator / Specialist` | 1,928 |
| Hiring `Safety Director` | 1,777 |
| Any of the five safety/EHS titles | **5,507** |

**5,507 people at companies with a live trigger, for zero extra cost and zero new code.**
Compare that with OSHA citations at 1–2 usable leads a month. Reported response rates for
trigger-based outreach run several times cold baseline; even discounting vendor numbers
heavily, this is the largest unexploited signal we have.

The opener writes itself and is verifiable: *"Saw you're hiring a Safety Manager —"*.

**Do this first.** It is a config change on an existing campaign, not a project.

---

## Signals ranked by what we can actually get

| Signal | Names a company? | Volume | Cost | State |
|---|---|---|---|---|
| **Hiring for safety/EHS roles** | Yes | ~5,500 in ICP | $0 — on the Apollo plan | **Ready, unused** |
| **OSHA news releases** | Yes | 1–2 good/month | $0 | **Built and running** |
| **Apollo Website Visitors** | Yes | 100 companies/mo | $0 — on the Apollo plan | **Unused, needs a script on the site** |
| EPA ECHO enforcement | Yes | Large | $0 | Real, but a day of work — see below |
| G2 Buyer Intent | Yes | Unknown | Paid add-on | Needs the listing claimed first |
| FMCSA carrier data | Yes | Large | $0 | Census only; safety events gated |
| LinkedIn comments on our posts | Yes (a person) | Depends on Sid | $0 | Parser built, mailbox missing |
| Google Alerts / F5Bot | **No — a page** | Low | $0 | Awareness only |
| Competitor brand alerts | **No — their PR** | Low | $0 | Weakest thing on the list |

---

## Apollo Website Visitors — already paid for, switched off

The Professional plan ($79/seat/mo, 48,000 credits/yr, ~42,200 unused) includes
**Website Visitors: identify 100 companies monthly**. That's reverse-IP company
identification: which businesses visited knowella.com without filling anything in.

It is second-party intent — the strongest kind, because it's about *us* rather than a
category. It needs a tracking script on the site and nothing else. 100 companies/month is
a small cap, but 100 companies that visited your pricing page beat 5,000 that didn't.

**Unverified:** I could not confirm from the API how the identified companies are
retrieved programmatically, or whether the 100/month cap is per seat. Check in the Apollo
UI before building anything against it.

---

## EPA ECHO — real, free, and messier than it looks

ECHO is the environmental half of EHS: Clean Air Act, Clean Water Act, RCRA, safe
drinking water. Roughly 1.5 million regulated facilities, 59 fields per record including
`FacPenaltyCount`, `FacDateLastPenalty`, `FacDateLastFormalAction`, `FacNAICSCodes`,
`FacInspectionCount` and per-programme compliance status.

**Verified working:** the REST service responds and completes a full round trip —
`get_facilities` returns a `QueryID`, `get_qid` returns the rows. A Texas query returned
451 facilities with significant violations, with names and street addresses.

**Verified problem, and it's the reason this isn't built yet:**

- The boolean filter parameters did not behave as documented in my probes. `p_penl=50000`
  and `p_fea=Y` both returned essentially unfiltered result sets (88,968 rows for Texas;
  19,736 for Maine, which is more facilities than Maine plausibly has under enforcement).
- The facility list is **not a company list**. Top results included `1636 INTERCONNECT
  ACRE SITE`, `0 TOWN FARM ROAD`, `(DUPLICATE DON'T USE) H.C.CROOKER & SO` and a long tail
  of dry cleaners. Brownfield sites, water systems and addresses sit alongside real
  employers.

**Conclusion:** the data is genuinely valuable and genuinely free, but the REST API is the
wrong door. The right approach is the **ECHO Exporter bulk download** (one zip, all
facilities, all fields) filtered locally on penalty date, penalty amount and NAICS. That's
a day of work, not an hour, and it should wait until the hiring signal is proven.

---

## FMCSA — census is open, safety events are not

For KnowDoc's carrier market.

| Endpoint | Result |
|---|---|
| `safer.fmcsa.dot.gov` | **403** to any non-browser client |
| `ai.fmcsa.dot.gov/SMS` | **403** |
| QCMobile API | **403** without a `webKey` — free registration required |
| **`data.transportation.gov`** | **200, no key** — Socrata API, JSON |

`data.transportation.gov` carries *Company Census File*, *Carrier – All With History* and
*Motor Carrier Registrations*. Real data, no key, no scraping — but it is **census**:
carrier name, DOT number, address, fleet size, mileage. It does **not** carry the safety
events that would make a trigger (out-of-service rates, CSA scores, compliance reviews).

For those you need the free QCMobile `webKey`. That's a registration form, not a
purchase — worth doing before any KnowDoc signal work.

---

## Competitor activity — the honest answer

**The category exists and it is enterprise-priced.** Bombora, 6sense, Demandbase,
ZoomInfo and TechTarget all sell intent data that flags accounts evaluating alternatives.
None are realistic at our stage.

**G2 Buyer Intent is the one that fits the shape of our business** — it flags when a
company views our profile, compares us against a competitor, or browses the category.
That is second-party intent about *us*, not a broad category signal. But it requires the
G2 listing to be claimed first, and buyer intent is a paid add-on above the free listing.

**Competitor Google Alerts are the weakest item we have researched.** What arrives is the
competitor's own press releases, funding announcements and product launches — their PR
team's output, in our queue. The valuable mention (a public comparison, a customer
complaining) is rare, and when it happens it usually happens inside a LinkedIn group or on
a review site, which is exactly where Google cannot see. Two or three of these, treated as
awareness, not pipeline.

**Ruled out:** identifying a competitor's customers by technology fingerprint
(BuiltWith/Wappalyzer style) works for tools that leave traces in a website's markup. EHS
platforms are internal systems behind a login — there is nothing to fingerprint.

---

## Google Alerts and RSS — closed, and why

Both were considered as an app intake and both were rejected on the same rule:

> **An intake earns its place only if it names someone you can contact.**

The trade RSS feeds were built, measured and removed: six publications delivered ~110
items a day, keyword filtering cut that to ~33, and not one of the 33 was a person. They
buried the signals that were.

Google Alerts fail the same test — they find *pages*. A keyword-scoped alert is more
precise than a whole trade publication, but that is a difference of degree, not kind, and
rebuilding a poller for them would reopen the door we just closed.

**Decision:** Google Alerts and F5Bot go to the shared mailbox on **email** delivery, and
reach the app through the same single inbound door as everything else if and when that is
built. No second intake, no poller. The digest parsers for both are already written and
tested (one alert email correctly becomes N signals).

The only thing still polled is OSHA, because it names a company.

---

## What to do, in order

1. **Switch on the hiring filter** on `knowella-safety-ai` and `knowdoc-freight`. Config
   change, no code, ~5,500 people with a live trigger.
2. **Put the Apollo tracking script on knowella.com.** Already paid for; 100 identified
   companies a month that we currently throw away.
3. **Claim the G2 and Capterra listings.** Free, and a precondition for any buyer-intent
   signal later — plus buyers search there regardless.
4. **Register for the FMCSA QCMobile webKey.** Free, five minutes, unblocks carrier safety
   triggers whenever KnowDoc needs them.
5. **Leave EPA ECHO until the hiring signal has been proven.** The data is good; the
   integration is a day, and it should not be spent before something simpler has shown
   whether trigger-based outreach converts at all for us.

**The measurement that decides everything:** every one of these lands in a campaign with a
`source_id`, so the Sources page compares it against the number that started this —
*Apollo cold: 4,422 leads, 4,226 sent, 9 replies, 0 meetings, 0.21%.* If hiring-triggered
outreach cannot beat that, the problem is the message, not the list.

---

## Sources

- [EPA ECHO web services](https://echo.epa.gov/tools/web-services) ·
  [ECHO data downloads](https://echo.epa.gov/tools/data-downloads)
- [FMCSA QCMobile API](https://mobile.fmcsa.dot.gov/QCDevsite/docs/qcApi) ·
  [data.transportation.gov catalog](https://data.transportation.gov/)
- [Hiring signals as a sales trigger](https://prospeo.io/s/hiring-signals-for-sales)
- [Intent data platform landscape](https://www.factors.ai/blog/top-intent-data-platforms)
- Apollo filter behaviour: live-probed, see `docs/outreach-campaign-fields-research.md`
