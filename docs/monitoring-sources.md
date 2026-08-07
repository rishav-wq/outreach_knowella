# Monitoring sources — where Knowella's buyers actually talk

*Researched 2026-08-06. Purpose: give Amatullah a concrete, do-able setup list for
"notify us when someone asks a question or comments," and feed the engage → capture →
nurture loop (see the architecture at the end).*

**The headline finding:** our buyers — safety managers, EHS directors, fleet/carrier
safety leads at industrial companies — are on **LinkedIn groups and trade publications**,
not on Reddit or Hacker News. Generic social-listening tools are aimed at the SaaS/dev
crowd and will mostly deliver noise for us.

---

## First: how "monitoring" works here — nothing on this list is scraped

Every source below **pushes to us**. There are exactly three channels, and it matters which
one a source uses, because only two of them tell you *a person asked something*.

| Channel | How it works | What it catches |
|---|---|---|
| **RSS** | The publisher hosts a machine-readable feed at a fixed URL, on purpose. We poll it. | New articles — **topic level** |
| **Google Alerts → RSS** | Google already crawled the web. In the alert, set *Deliver to → RSS feed* and you get a pollable URL instead of email. | Any public page mentioning a keyword, incl. indexed forum threads — **topic level** |
| **Notification email** | The platform emails us: "X commented on your post", "someone asked a question about your product", "new review". | **Person level** — a named human with a question |

The third channel is the only automatic one that answers *"notify us when someone asks a
question"* — and it only fires **where we have an account and a presence**: our LinkedIn
page and posts, our G2/Capterra listing, our Trustpilot profile. That reframes the whole
exercise: you don't monitor the internet for questions, you become the place questions get
asked, and the platform notifies you.

Which is why **Tier 2 is human-monitored, and that is the mechanism, not a shortcut.** Sid
joins the group → switches on its notifications → LinkedIn emails him when someone posts or
comments → he answers → the extension captures whoever engaged. There is no feed to poll:
membership is the API. See *Explicitly ruled out* for why no tool can do this instead.

---

## Tier 1 — automate today, free (about one hour of setup)

### A. RSS feeds → Feedly or Inoreader (email/Slack digest)

| Publication | Why |
|---|---|
| [EHS Today](https://www.ehstoday.com/) | Endeavor's flagship for manufacturing/construction EHS |
| [Safety+Health](https://www.safetyandhealthmagazine.com/) | National Safety Council, ~92,000 subscribers |
| [Occupational Health & Safety](https://ohsonline.com/) | Industry news + webinars |
| [FreightWaves](https://www.freightwaves.com/) | Freight/logistics news, big practitioner audience |
| [Overdrive](https://www.overdriveonline.com/) | Owner-operator and carrier coverage |
| [Trucking Dive](https://www.truckingdive.com/) | Carrier/fleet business news |
| [CDLLife](https://www.cdllife.com/) | 2M+ Facebook followers, driver-side sentiment |

Shortcuts — pre-built lists to import:
- [Feedspot: Top 100 Trucking RSS Feeds](https://rss.feedspot.com/trucking_rss_feeds/)
- [Feedspot: Top 15 Occupational Health & Safety magazines](https://magazine.feedspot.com/occupational_health_and_safety_magazines/)

### B. Google Alerts (free)

Set **Deliver to → RSS feed** on each one (not email) — that gives a URL the app can poll,
and keeps the alerts out of a person's inbox. Create one alert each for:
- `Knowella` (brand)
- Competitors: `VelocityEHS`, `Intelex`, `Cority`, `EHS Insight`, `SafetyCulture`, `Samsara`
- Category phrases: `"OSHA recordkeeping software"`, `"fleet safety compliance software"`,
  `"CSA score improvement"`, `"EHS software"` + `trucking` / `manufacturing`

### C. Native notifications — already ours, just switch on

**The only automatic person-level signal we get.** Each of these emails us when a named
human does something; nothing is polled or scraped.

- **G2 / Capterra** — new review and buyer-question alerts
- **LinkedIn** — company page mentions + comments on our own posts *(highest-value single
  source: it is exactly where the capture extension then works)*
- **Trustpilot** — if we claim a profile

Point them all at one address so they land in a single queue rather than five inboxes.

### D. F5Bot (free) — Reddit + Hacker News keyword alerts

Low yield for our ICP, but it costs nothing and catches the occasional competitor thread.

---

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

Detection is bought, not built (Feedly, Alerts, native notifications). What we build is the
attribution spine — so we can see which of these sources actually produces meetings, and
spend the next hour where it pays.

**Second compounding leg:** the questions people ask in these threads are the newsletter and
LinkedIn-post backlog, written by the buyers themselves. Log them against the source.
