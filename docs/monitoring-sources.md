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

### A. RSS feeds — built into the app (Signals → Feeds)

No Feedly account needed: the app polls these itself every 30 minutes and files
matches in the Signals queue. **Signals → Queue → "Add the 6 verified feeds"** adds
the whole set in one click. Every URL below was fetched and parsed on 2026-08-07.

| Publication | Feed URL | Why |
|---|---|---|
| EHS Today | `https://www.ehstoday.com/__rss/website-scheduled-content.xml?input=%7B%22sectionAlias%22%3A%22home%22%7D` | Endeavor's flagship for manufacturing/construction EHS |
| Safety+Health | `https://www.safetyandhealthmagazine.com/feed/` | National Safety Council, ~92,000 subscribers |
| Occupational Health & Safety | `https://ohsonline.com/rss-feeds/news.aspx` | Industry news + webinars |
| FreightWaves | `https://www.freightwaves.com/feed` | Freight/logistics news, big practitioner audience |
| Trucking Dive | `https://www.truckingdive.com/feeds/news/` | Carrier/fleet business news |
| CDLLife | `https://cdllife.com/feed/` | 2M+ Facebook followers, driver-side sentiment |

**Overdrive is deliberately missing.** `overdriveonline.com` returns 403 to any
non-browser client (Cloudflare), so it cannot be polled. Read it by hand or skip it.

More to add later, if the six aren't enough:
- [Feedspot: Top 100 Trucking RSS Feeds](https://rss.feedspot.com/trucking_rss_feeds/)
- [Feedspot: Top 15 Occupational Health & Safety magazines](https://magazine.feedspot.com/occupational_health_and_safety_magazines/)

Add keywords to a feed to filter it (`OSHA, recordkeeping, CSA`); leave them blank to
keep everything.

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

Point them all at one address so they land in a single queue rather than five inboxes —
literally: forward them to the app's inbound address and they become Signals, parsed into
who asked, on what platform, with a link. Setup:

1. In Postmark, add an inbound address (or an inbound domain) and set its webhook to
   `https://outreach.knowella.com/api/signals/inbound?token=YOUR_TOKEN`.
2. On the VM, **append** the token — never overwrite the file:
   `echo 'SIGNALS_WEBHOOK_TOKEN=YOUR_TOKEN' | sudo tee -a /opt/outreach-agent/.env`
3. Forward (or auto-forward a filter for) LinkedIn / G2 / Trustpilot notification mail there.

Mail we can't parse is filed under its subject line rather than dropped, so a changed
notification format costs us the labelling and never the lead.

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
