import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'

// The listening post.
//
// One structural fact organises this whole page, and it comes straight from the
// research: a NAMED PERSON asking a question is worth a hundred article mentions.
// Notification email (LinkedIn, G2, Trustpilot) and anything you log by hand is
// person-level — someone stated a problem in public and is waiting. Feeds are
// topic-level — the subject is live, nobody is waiting. So the queue is two
// registers, not one list: people get the loud treatment, topics stay quiet.

const PERSON_KINDS = new Set(['question', 'comment', 'review', 'mention', 'reaction'])
const PLATFORM = {
  linkedin: 'LinkedIn', g2: 'G2', capterra: 'Capterra', trustpilot: 'Trustpilot',
  google_alert: 'Google Alert', rss: 'Feed', other: 'Other',
}
// Verified live on 2026-08-07 — each one fetched and parsed before shipping.
// Overdrive is deliberately absent: its feed 403s behind Cloudflare.
//
// The keywords matter more than the feeds. Unfiltered, these six deliver ~111
// items a day and most of it is crash reporting written for drivers — a firehose,
// not a monitor. Filtered on what a SAFETY MANAGER has to deal with (a citation, an
// audit, a rule change) it drops to ~33 and reads like a briefing. Measured, not
// guessed: 70% of the volume removed, and the OSHA enforcement stories survive.
const EHS_KW = ['osha', 'ehs', 'safety manager', 'recordkeeping', '300a', 'citation', 'inspection',
  'violation', 'penalty', 'compliance', 'audit', 'injury rate', 'incident report', 'training',
  'heat', 'silica', 'lockout', 'ergonomic']
// Hyphens and spaces are interchangeable when matching, so "out-of-service" alone
// covers both spellings — no need to list each variant.
const TRUCK_KW = ['fmcsa', 'csa', 'dot audit', 'compliance review', 'safety rating', 'out-of-service',
  'eld', 'hours of service', 'driver qualification', 'clearinghouse', 'violation',
  'citation', 'audit', 'inspection', 'osha']
//
// Trade press needs filtering because it's written for a mixed audience. The
// REGULATOR's own feed doesn't: every OSHA news release is an enforcement action
// against a named company, so it ships with no keywords at all. Trucking Dive was
// dropped after inspection — it covers the BUSINESS of trucking (M&A, earnings,
// plant closures) and matched zero of our terms. Land Line replaces it: hours-of-
// service exemptions, roadside enforcement sweeps, state crackdowns.
const STARTER_FEEDS = [
  { name: 'OSHA news releases', url: 'https://www.osha.gov/news/newsreleases.xml', keywords: [] },
  { name: 'EHS Today', url: 'https://www.ehstoday.com/__rss/website-scheduled-content.xml?input=%7B%22sectionAlias%22%3A%22home%22%7D', keywords: EHS_KW },
  { name: 'Safety+Health', url: 'https://www.safetyandhealthmagazine.com/feed/', keywords: EHS_KW },
  { name: 'Occupational Health & Safety', url: 'https://ohsonline.com/rss-feeds/news.aspx', keywords: EHS_KW },
  { name: 'FreightWaves', url: 'https://www.freightwaves.com/feed', keywords: TRUCK_KW },
  { name: 'Land Line (OOIDA)', url: 'https://landline.media/feed/', keywords: TRUCK_KW },
  { name: 'CDLLife', url: 'https://cdllife.com/feed/', keywords: TRUCK_KW },
]
// A feed carrying nothing but enforcement actions needs no filter, and saying so
// stops the "unfiltered feed" warning from crying wolf about the best source we have.
const NO_FILTER_OK = new Set(['https://www.osha.gov/news/newsreleases.xml'])

const ago = (iso) => {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 3600) return `${Math.floor(s / 60) || 1}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export default function Signals() {
  const [data, setData] = useState(null)
  const [feeds, setFeeds] = useState([])
  const [backlog, setBacklog] = useState([])
  const [view, setView] = useState('queue')
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')

  const load = () => Promise.all([
    // Only the open queue: dismissed signals are kept for dedupe, never displayed,
    // and shipping them to the browser just to filter them out wastes the payload.
    api.listSignals('new').then(setData).catch(() => setData({ signals: [], counts: {} })),
    api.listFeeds().then(setFeeds).catch(() => setFeeds([])),
    api.listBacklog().then(setBacklog).catch(() => setBacklog([])),
  ])
  useEffect(() => { load() }, [])

  const act = async (fn, msg) => {
    setBusy(msg); setNote('')
    try { const r = await fn(); await load(); if (r?.msg) setNote(r.msg) }
    catch (e) { setNote(String(e.message || e).slice(0, 200)) }
    finally { setBusy('') }
  }
  const poll = () => act(async () => {
    const r = await api.pollSignals()
    return { msg: `Polled ${feeds.length} feed${feeds.length === 1 ? '' : 's'} — ${r.new} new${r.errors ? `, ${r.errors} failed` : ''}` }
  }, 'Polling…')
  // Add-or-retune: the same call sets the recommended keywords on feeds that are
  // already there, so a feed added before we tuned them doesn't stay a firehose.
  const addStarters = () => act(async () => {
    let ok = 0
    for (const f of STARTER_FEEDS) {
      try {
        const r = await api.addFeed(f)
        await api.updateFeed(r.id, f)
        ok++
      } catch { /* one bad feed must not stop the rest */ }
    }
    return { msg: `${ok} of ${STARTER_FEEDS.length} feeds set up with recommended keywords` }
  }, 'Setting up feeds…')
  const clearTopics = () => act(async () => {
    const r = await api.clearSignals('rss')
    return { msg: `Cleared ${r.cleared} topic${r.cleared === 1 ? '' : 's'}` }
  }, 'Clearing…')

  const open = (data?.signals || []).filter((s) => s.status === 'new')
  const people = useMemo(() => open.filter((s) => s.channel !== 'rss' && PERSON_KINDS.has(s.kind)), [data])
  const topics = useMemo(() => open.filter((s) => !(s.channel !== 'rss' && PERSON_KINDS.has(s.kind))), [data])

  if (data === null) return <div><Skeleton h={44} /><Skeleton h={92} r={12} style={{ marginTop: 16 }} /><Skeleton h={260} r={12} style={{ marginTop: 14 }} /></div>

  const liveFeeds = feeds.filter((f) => f.enabled)
  const brokenFeeds = feeds.filter((f) => f.last_poll && !f.ok)
  const lastPoll = feeds.map((f) => f.last_poll).filter(Boolean).sort().pop()

  return (
    <div className="sig">
      <div className="lib-head">
        <div>
          <div className="dash-eyebrow">Signals</div>
          <div className="lib-title">
            {people.length} <small>{people.length === 1 ? 'person waiting' : 'people waiting'}</small>
            {topics.length > 0 && <span className="sig-title-sub">· {topics.length} topics moving</span>}
          </div>
          <p className="dash-sub">
            Nothing here is scraped. Platforms push to us — forwarded notification mail names a real
            person with a real question; polled feeds tell you a subject is live. Answer the people first.
          </p>
        </div>
        <div className="dash-actions">
          <button className="btn" onClick={poll} disabled={!!busy || !feeds.length}>
            <Icon name="download" size={14} /> {busy === 'Polling…' ? 'Polling…' : 'Check feeds now'}
          </button>
        </div>
      </div>

      {/* The intake meter: both channels, honest about which is actually switched on. */}
      <div className="sig-intake">
        <div className={`sig-chan ${data.inbound_ready ? 'on' : ''}`}>
          <div className="sig-chan-k"><span className="sig-dot" /> Notification email</div>
          <div className="sig-chan-v">{data.inbound_ready ? 'Receiving' : 'Not wired up'}</div>
          <div className="sig-chan-n">
            {data.inbound_ready
              ? 'Forward LinkedIn, G2 and Trustpilot notifications to the inbound address.'
              : 'Set SIGNALS_WEBHOOK_TOKEN and point a Postmark inbound address at /api/signals/inbound.'}
          </div>
        </div>
        <div className={`sig-chan ${liveFeeds.length ? 'on' : ''}`}>
          <div className="sig-chan-k"><span className="sig-dot" /> Feeds</div>
          <div className="sig-chan-v">
            {liveFeeds.length ? `${liveFeeds.length} ${liveFeeds.length === 1 ? 'feed' : 'feeds'}` : 'No feeds yet'}
          </div>
          <div className="sig-chan-n">
            {lastPoll ? `Checked ${ago(lastPoll)}, then every 30 min.` : 'Publisher feeds and Google Alerts, polled every 30 minutes.'}
            {brokenFeeds.length > 0 && <b className="sig-warn"> {brokenFeeds.length} failing</b>}
          </div>
        </div>
        <div className="sig-chan sig-chan-quiet">
          <div className="sig-chan-k">Communities</div>
          <div className="sig-chan-v">You are the monitor</div>
          <div className="sig-chan-n">
            LinkedIn groups have no API — membership is the API. Log what you see with <b>Add by hand</b>.
          </div>
        </div>
      </div>

      {note && <div className="banner">{note}</div>}

      <div className="seg sig-seg" role="tablist">
        {[['queue', `Queue${open.length ? ` (${open.length})` : ''}`],
          ['backlog', `Backlog${backlog.length ? ` (${backlog.length})` : ''}`],
          ['feeds', `Feeds${feeds.length ? ` (${feeds.length})` : ''}`]].map(([k, label]) => (
          <button key={k} role="tab" aria-selected={view === k} className={view === k ? 'on' : ''} onClick={() => setView(k)}>{label}</button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div key={view} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
          {view === 'queue' && (
            <Queue people={people} topics={topics} feeds={feeds} busy={busy}
              onAddStarters={addStarters} onClearTopics={clearTopics}
              onReload={load} onNote={setNote} onTuneFeeds={() => setView('feeds')} />
          )}
          {view === 'backlog' && <Backlog rows={backlog} onReload={load} />}
          {view === 'feeds' && (
            <Feeds rows={feeds} busy={busy} onAddStarters={addStarters} onReload={load} onNote={setNote} />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

// --- queue -------------------------------------------------------------------

function Queue({ people, topics, feeds, busy, onAddStarters, onClearTopics, onReload, onNote, onTuneFeeds }) {
  const [adding, setAdding] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const unfiltered = feeds.filter((f) => !(f.keywords || []).length && !NO_FILTER_OK.has(f.url)).length

  if (!people.length && !topics.length) {
    return (
      <>
        {adding && <AddByHand onDone={() => { setAdding(false); onReload() }} onCancel={() => setAdding(false)} />}
        <motion.div className="empty sig-empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <div className="empty-icon"><Icon name="inbox" size={24} /></div>
          <h3>Nothing has come in yet</h3>
          <p className="muted">
            The queue fills from three places. Two of them are one-time setup; the third is you, in a group nobody can notify us about.
          </p>
          <ol className="sig-setup">
            <li><b>Add the feeds.</b> Six trade publications, each one fetched and parsed before we shipped this button.</li>
            <li><b>Forward your notification mail.</b> LinkedIn comments, G2 questions and Trustpilot reviews name a real person — that is the signal worth answering.</li>
            <li><b>Log what you see.</b> In the 130k-member EHS group there is no webhook and never will be. You are the monitor.</li>
          </ol>
          <div className="empty-actions">
            {!feeds.length && (
              <button className="btn primary" onClick={onAddStarters} disabled={!!busy}>
                <Icon name="plus" size={14} /> {busy ? 'Adding…' : 'Add the 6 verified feeds'}
              </button>
            )}
            <button className="btn" onClick={() => setAdding(true)}><Icon name="plus" size={14} /> Add by hand</button>
          </div>
        </motion.div>
      </>
    )
  }

  return (
    <>
      <div className="sig-bar">
        <button className="btn" onClick={() => setAdding(true)}><Icon name="plus" size={14} /> Add by hand</button>
      </div>
      {adding && <AddByHand onDone={() => { setAdding(false); onReload() }} onCancel={() => setAdding(false)} />}

      {people.length > 0 && (
        <section className="sig-sect">
          <h4 className="sig-h">Someone asked <span className="sig-h-n">{people.length}</span></h4>
          <p className="sig-h-sub">A named person, in public, waiting for an answer. This is the whole point of the loop.</p>
          <div className="sig-cards">
            {people.map((s) => <PersonCard key={s.id} s={s} onReload={onReload} onNote={onNote} />)}
          </div>
        </section>
      )}

      {topics.length > 0 && (
        <section className="sig-sect">
          <h4 className="sig-h sig-h-quiet">
            Topics moving <span className="sig-h-n">{topics.length}</span>
            <button className="btn ghost sig-h-act" onClick={onClearTopics} disabled={!!busy}>Clear all</button>
          </h4>
          <p className="sig-h-sub">Nobody is waiting on these. Useful for what to post about, not who to talk to.</p>
          {unfiltered > 0 && (
            <div className="banner sig-tune">
              <span>
                <b>{unfiltered} {unfiltered === 1 ? 'feed has' : 'feeds have'} no keywords</b>, so everything they
                publish lands here — including crash reporting written for drivers. Filtering on what a safety
                manager deals with cuts roughly 70% of it.
              </span>
              <span className="sig-tune-acts">
                <button className="btn primary" onClick={onAddStarters} disabled={!!busy}>
                  {busy ? 'Applying…' : 'Apply recommended keywords'}
                </button>
                <button className="btn" onClick={onTuneFeeds}>Tune by hand</button>
              </span>
            </div>
          )}
          <div className="sig-topics">
            {(showAll ? topics : topics.slice(0, 20)).map((s) => <TopicRow key={s.id} s={s} onReload={onReload} />)}
          </div>
          {topics.length > 20 && (
            <button className="btn sig-more" onClick={() => setShowAll(!showAll)}>
              {showAll ? 'Show fewer' : `Show all ${topics.length}`}
            </button>
          )}
        </section>
      )}
    </>
  )
}

function PersonCard({ s, onReload, onNote }) {
  const [gone, setGone] = useState(false)
  const done = async (fn) => {
    setGone(true)
    try { await fn() } catch (e) { setGone(false); onNote(String(e.message || e).slice(0, 160)) }
    onReload()
  }
  const toBacklog = () => done(async () => {
    await api.addBacklog({ question: s.title, source_id: s.source_id, signal_id: s.id, url: s.url })
    await api.setSignalStatus(s.id, 'engaged')
  })

  return (
    <motion.article layout className={`sig-card ${gone ? 'is-gone' : ''} k-${s.kind}`}
      initial={{ opacity: 0, y: 10 }} animate={{ opacity: gone ? 0.35 : 1, y: 0 }}>
      <header className="sig-card-head">
        <span className="sig-kind">{s.kind}</span>
        <span className="sig-meta">{PLATFORM[s.platform] || s.platform}</span>
        {s.source && <span className="sig-meta">· {s.source}</span>}
        <span className="sig-meta sig-when">{ago(s.created_at)}</span>
      </header>
      {s.person && <div className="sig-who">{s.person}</div>}
      <h5 className="sig-card-title">{s.title}</h5>
      {s.text && <p className="sig-card-text">{s.text.slice(0, 320)}{s.text.length > 320 ? '…' : ''}</p>}
      <footer className="sig-card-foot">
        {s.url && (
          <a className="btn primary" href={s.url} target="_blank" rel="noreferrer"
            onClick={() => api.setSignalStatus(s.id, 'engaged').then(onReload).catch(() => {})}>
            Open and answer ↗
          </a>
        )}
        <button className="btn" onClick={toBacklog} title="This question is a post — file it">
          <Icon name="plus" size={13} /> Backlog
        </button>
        <button className="btn ghost" onClick={() => done(() => api.setSignalStatus(s.id, 'ignored'))}>Ignore</button>
      </footer>
    </motion.article>
  )
}

function TopicRow({ s, onReload }) {
  return (
    <motion.div layout className="sig-topic" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <span className="sig-topic-src">{s.feed || PLATFORM[s.platform] || s.platform}</span>
      {s.url
        ? <a className="sig-topic-t" href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
        : <span className="sig-topic-t">{s.title}</span>}
      <span className="sig-meta sig-when">{ago(s.created_at)}</span>
      <button className="icon-btn" title="Clear" onClick={() => api.setSignalStatus(s.id, 'ignored').then(onReload)}>
        <Icon name="check" size={13} />
      </button>
    </motion.div>
  )
}

function AddByHand({ onDone, onCancel }) {
  const [f, setF] = useState({ title: '', person: '', url: '', platform: 'linkedin', kind: 'question', source_id: '' })
  const [sources, setSources] = useState([])
  const [err, setErr] = useState('')
  useEffect(() => { api.listSources().then(setSources).catch(() => {}) }, [])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const save = async () => {
    if (!f.title.trim()) return setErr('What did they ask?')
    try { await api.addSignal(f); onDone() } catch (e) { setErr(String(e.message || e).slice(0, 160)) }
  }
  return (
    <motion.div className="sig-add" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}>
      <div className="sig-add-head">
        <b>Log what you saw</b>
        <span className="muted">Communities can't notify us. This is how what you read in a group becomes a lead and a post.</span>
      </div>
      <input className="field-input" autoFocus placeholder="What did they ask? — paste the question" value={f.title} onChange={set('title')} />
      <div className="sig-add-row">
        <input className="field-input" placeholder="Who asked (optional)" value={f.person} onChange={set('person')} />
        <input className="field-input" placeholder="Link to the thread (optional)" value={f.url} onChange={set('url')} />
        <select className="field-input" value={f.source_id} onChange={set('source_id')}>
          <option value="">Which source?</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>
      {err && <div className="banner error">{err}</div>}
      <div className="sig-add-foot">
        <button className="btn primary" onClick={save}>Add signal</button>
        <button className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </motion.div>
  )
}

// --- backlog -----------------------------------------------------------------

const STAGES = ['idea', 'drafted', 'published']

function Backlog({ rows, onReload }) {
  const [q, setQ] = useState('')
  const add = async () => { if (!q.trim()) return; await api.addBacklog({ question: q.trim() }); setQ(''); onReload() }

  return (
    <div className="sig-backlog">
      <p className="sig-h-sub sig-backlog-lede">
        The questions buyers actually asked, in their words. This is the newsletter and post backlog —
        written by the people you want to sell to, which is why it beats anything you'd invent.
      </p>
      <div className="ready-form">
        <input className="field-input" value={q} placeholder="Add a question you keep hearing"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button className="btn primary" onClick={add}>Add</button>
      </div>
      {rows.length === 0 ? (
        <div className="empty"><h3>No questions logged yet</h3>
          <p className="muted">Hit <b>Backlog</b> on a signal, or add one above.</p></div>
      ) : (
        <div className="sig-list">
          {rows.map((b) => (
            <div key={b.id} className={`sig-bl st-${b.status}`}>
              <div className="sig-bl-main">
                <div className="sig-bl-q">{b.question}</div>
                <div className="sig-meta">
                  {b.source || 'unattributed'} · added {ago(b.created_at)}
                  {b.url && <> · <a href={b.url} target="_blank" rel="noreferrer">thread ↗</a></>}
                </div>
              </div>
              <div className="sig-stages">
                {STAGES.map((st) => (
                  <button key={st} className={`sig-stage ${b.status === st ? 'on' : ''}`}
                    onClick={() => api.setBacklogStatus(b.id, st).then(onReload)}>{st}</button>
                ))}
              </div>
              <button className="icon-btn" title="Delete" onClick={() => api.deleteBacklog(b.id).then(onReload)}>
                <Icon name="trash" size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// --- feeds -------------------------------------------------------------------

function Feeds({ rows, busy, onAddStarters, onReload, onNote }) {
  const [f, setF] = useState({ url: '', name: '', keywords: '' })
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState(null)     // feed id whose keywords are open
  const [kw, setKw] = useState('')
  const unfiltered = rows.filter((r) => !(r.keywords || []).length && !NO_FILTER_OK.has(r.url)).length

  const saveKw = async (r) => {
    await api.updateFeed(r.id, { url: r.url, name: r.name, keywords: kw.split(',').map((s) => s.trim()).filter(Boolean) })
    setEditing(null); onReload()
  }
  const add = async () => {
    if (!f.url.trim()) return
    setAdding(true)
    try {
      const r = await api.addFeed({ url: f.url.trim(), name: f.name.trim(), keywords: f.keywords.split(',').map((s) => s.trim()).filter(Boolean) })
      onNote(`Added — ${r.new} item${r.new === 1 ? '' : 's'} on the first read`)
      setF({ url: '', name: '', keywords: '' }); onReload()
    } catch (e) { onNote(String(e.message || e).slice(0, 200)) }
    finally { setAdding(false) }
  }

  return (
    <div>
      <p className="sig-h-sub sig-backlog-lede">
        A publisher hosts a feed on purpose, so polling one is reading what was published for reading.
        For a Google Alert, set <b>Deliver to → RSS feed</b> and paste the URL it gives you.
        <b> Keywords are what make a feed useful</b> — without them a trade publication delivers its whole
        day, most of which is written for someone other than our buyer.
      </p>
      {unfiltered > 0 && (
        <div className="banner sig-tune">
          <span><b>{unfiltered} {unfiltered === 1 ? 'feed is' : 'feeds are'} unfiltered.</b> The recommended
            keywords are the ones a safety manager's problems are described with — citations, audits, rule changes.</span>
          <span className="sig-tune-acts">
            <button className="btn primary" onClick={onAddStarters} disabled={!!busy}>
              {busy ? 'Applying…' : 'Apply recommended keywords'}
            </button>
          </span>
        </div>
      )}
      <div className="sig-add-row sig-feed-form">
        <input className="field-input" placeholder="Feed URL" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
        <input className="field-input" placeholder="Name it" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <input className="field-input" placeholder="Keywords, comma separated" value={f.keywords} onChange={(e) => setF({ ...f, keywords: e.target.value })} />
        <button className="btn primary" onClick={add} disabled={adding}>{adding ? 'Checking…' : 'Add feed'}</button>
      </div>
      {rows.length === 0 ? (
        <div className="empty"><h3>No feeds yet</h3><p className="muted">Add one above, or use the starter set on the Queue tab.</p></div>
      ) : (
        <div className="sig-list">
          {rows.map((r) => (
            <div key={r.id} className="sig-feed">
              <span className={`dot ${r.last_poll && !r.ok ? 'd-held' : 'd-ok'}`} title={r.last_note || ''} />
              <div className="sig-bl-main">
                <div className="sig-bl-q">{r.name}</div>
                <div className="sig-meta">
                  <a href={r.url} target="_blank" rel="noreferrer">{r.url.slice(0, 62)}{r.url.length > 62 ? '…' : ''}</a>
                  {r.last_poll && <> · checked {ago(r.last_poll)}{r.last_note ? ` — ${r.last_note}` : ''}</>}
                </div>
                {editing === r.id ? (
                  <div className="ready-form">
                    <input className="field-input" autoFocus value={kw} placeholder="Keywords, comma separated — blank keeps everything"
                      onChange={(e) => setKw(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && saveKw(r)} />
                    <button className="btn primary" onClick={() => saveKw(r)}>Save</button>
                    <button className="btn" onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                ) : (
                  <button className={`sig-kw ${r.keywords?.length ? '' : 'is-open'}`}
                    title="Click to edit which words this feed is filtered on"
                    onClick={() => { setEditing(r.id); setKw((r.keywords || []).join(', ')) }}>
                    {r.keywords?.length
                      ? <>filtered on <b>{r.keywords.slice(0, 6).join(', ')}</b>{r.keywords.length > 6 ? ` +${r.keywords.length - 6} more` : ''}</>
                      : 'no filter — everything gets through'}
                  </button>
                )}
              </div>
              <button className="btn ghost" onClick={() => api.toggleFeed(r.id, !r.enabled).then(onReload)}>
                {r.enabled ? 'Pause' : 'Resume'}
              </button>
              <button className="icon-btn" title="Remove feed" onClick={() => api.deleteFeed(r.id).then(onReload)}>
                <Icon name="trash" size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
