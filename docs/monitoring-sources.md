# Monitoring sources — where Knowella's buyers actually talk

*Researched 2026-08-06. Purpose: give Amatullah a concrete, do-able setup list for
"notify us when someone asks a question or comments," and feed the engage → capture →
nurture loop (see the architecture at the end).*

**The headline finding:** our buyers — safety managers, EHS directors, fleet/carrier
safety leads at industrial companies — are on **LinkedIn groups and trade publications**,
not on Reddit or Hacker News. Generic social-listening tools are aimed at the SaaS/dev
crowd and will mostly deliver noise for us.

---

## First: how "monitoring" works here — nothing is scraped, and one rule decides everything

**An intake earns its place only if it names someone you can contact.**

That rule is why this list is shorter than it was. Trade RSS feeds were built and then
removed: six publications delivered ~110 items a day, filtering cut that to ~33, and not
one of the 33 was a person you could email. They buried the signals that were.

Everything now arrives by **email**, through one Postmark inbound address:

| Source | What it gives you | Level |
|---|---|---|
| **LinkedIn notifications** | "X commented on your post", mentions of the company page | **person** |
| **G2 / Capterra / Trustpilot** | a new review, a buyer question on our listing | **person** |
| **Add by hand** (in the app) | what Sid read in a group no webhook can reach | **person** |
| **Google Alerts** (email delivery) | any public page matching a keyword | page |
| **F5Bot** (free) | Reddit / Hacker News keyword hits | page |

Digests are split: one Google Alert carrying eight results becomes eight signals, not one.

The only thing still polled is **OSHA news releases**, and only because every item is a
named employer that was just cited — a lead, not an article. It's built in, not a feed
you configure.

Person-level signals only fire **where we have an account and a presence** — our page,
our posts, our listing. You don't monitor the internet for questions; you become the
place questions get asked, and the platform tells you. Which is why **Tier 2 is
human-monitored, and that is the mechanism, not a shortcut.** Sid joins the group →
switches on notifications → LinkedIn emails him → he answers → the extension captures
whoever engaged. Membership is the API.

### Setup — one address, everything points at it

1. In Postmark, add an inbound address and set its webhook to
   `https://outreach.knowella.com/api/signals/inbound?token=YOUR_TOKEN`.
2. On the VM, **append** the token — never overwrite the file:
   `echo 'SIGNALS_WEBHOOK_TOKEN=YOUR_TOKEN' | sudo tee -a /opt/outreach-agent/.env`
3. Forward LinkedIn / G2 / Trustpilot notification mail there. Create the Google Alerts
   on **email** delivery (not RSS) addressed to it. Sign up for F5Bot with it.
4. Claim the review listings under a **role address**, not a personal one.

Mail we can't parse keeps its subject line rather than being dropped, so a changed
notification format costs us the labelling and never the lead.


## Tier 2 — where the buyers actually are (human presence, no API)

**None of these can be scraped or API-monitored** — LinkedIn has no groups API, Facebook
closed group access in 2018, and community platforms are membership-gated. These require a
human (Sid) to join, watch and answer. That is the point: the engagement is the moat, and
the extension captures whoever engages back.

| Community | Scale / note |
|---|---|
| EHS/Quality global LinkedIn group | **130,000+ members** |
| EHSQ Elite (LinkedIn) | 83,000 |
| Occupational Health & Safety Network (LinkedIn) | 34,000 |
| [EHS Today Networking Group](https://en.wikipedia.org/wiki/EHS_Today) | publisher-run discussion community |
| [NAEM](https://www.naem.org/) | EHS leaders from **800+ companies**, most of the Fortune 500 |
| [Nexus HSE](https://nexushse.com/) | practitioner-run; "EHS Shop Talk" sessions |
| [EHS Leadership Forum](https://www.skool.com/ehs-leadership-forum-6601/welcome-to-the-ehs-leadership-forum) (Skool) | Q&A format |
| [ASSP](https://www.assp.org/) | 151 chapters, 75 countries |
| [Trucksafe](https://trucksafe.com/) community | carrier safety managers + risk advisors — **exactly KnowDoc's buyer** |
| [TruckersReport forum](https://www.thetruckersreport.com/truckingindustryforum/) | drivers/owner-ops; active FMCSA-audit threads |

---

## Tier 3 — paid tools, only if Tier 1 proves insufficient

| Tool | Cost | Covers |
|---|---|---|
| [Syften](https://syften.com/) | ~$15–50/mo | Reddit-first + forums, live alerts |
| MentionDrop | ~$29/mo | Reddit + Google News + open web |
| Octolens | ~$119–159/mo | 13+ platforms, AI relevance scoring |
| Mention | varies | social, news, blogs, forums, 75+ review sites |

Run Tier 1 for a month first. If the LinkedIn + review-site notifications already produce
more than we can answer, paid tools add noise, not value.

---

## Explicitly ruled out (researched, not viable)

| Source | Why not |
|---|---|
| **Reddit API** | ~$12,000/yr, 2–4 week approval; May 2026 made unauthorized scraping an explicit Rule 8 violation and killed the free unauthenticated endpoints |
| **Trustpilot API** | Enterprise-only, ~$6k–30k/yr |
| **G2 API** | No public API; heavy anti-bot |
| **LinkedIn (groups/jobs) scraping** | No read API. Proxycurl shut down permanently in July 2025 after LinkedIn's federal lawsuit |
| **Facebook groups** | Graph API access closed since 2018 |
| **YouTube comments** | Free API (10k units/day) but commenters are display names — cannot be enriched into leads |

**Pattern:** comment-mining converts to leads only where the platform requires real
identity. That is LinkedIn, and essentially nowhere else — which is why the capture
extension exists and why the rest of this list is for *listening*, not harvesting.

---

## How this feeds the pipeline

```
DETECT (this document)  →  ENGAGE (Sid answers, in the thread)
      →  CAPTURE (extension: commenters + reactors, tagged with the source)
      →  ENRICH + ICP filter + dedup + suppression
      →  LIBRARY  →  NURTURE (blasts) / SALES (sequences)
      →  ATTRIBUTION per source  →  tells us where to engage next
```

All of it now lands in the app:

- **Signals** — the queue. Two registers, because the difference matters: *someone asked*
  (a named person, waiting) above *topics moving* (an article, nobody waiting). Answer the
  people; skim the topics.
- **Backlog** — a signal that's a question becomes a content item (idea → drafted →
  published). The buyers write our editorial calendar.
- **Sources** — what each place actually produced, leads through to meetings.

**The baseline to beat.** Attribution was backfilled over the existing database on
2026-08-07: *Apollo search — 4,422 leads, 4,226 sent, 9 replies, 0 meetings.* A 0.2% reply
rate is what buying a list gets you. Every LinkedIn group and community below is measured
against that number, on the same page, in the same columns.

**Second compounding leg:** the questions people ask in these threads are the newsletter and
LinkedIn-post backlog, written by the buyers themselves.
