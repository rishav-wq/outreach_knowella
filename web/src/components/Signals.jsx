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
const STARTER_FEEDS = [
  { name: 'EHS Today', url: 'https://www.ehstoday.com/__rss/website-scheduled-content.xml?input=%7B%22sectionAlias%22%3A%22home%22%7D' },
  { name: 'Safety+Health', url: 'https://www.safetyandhealthmagazine.com/feed/' },
  { name: 'Occupational Health & Safety', url: 'https://ohsonline.com/rss-feeds/news.aspx' },
  { name: 'FreightWaves', url: 'https://www.freightwaves.com/feed' },
  { name: 'Trucking Dive', url: 'https://www.truckingdive.com/feeds/news/' },
  { name: 'CDLLife', url: 'https://cdllife.com/feed/' },
]

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
    api.listSignals().then(setData).catch(() => setData({ signals: [], counts: {} })),
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
  const addStarters = () => act(async () => {
    let ok = 0
    for (const f of STARTER_FEEDS) { try { await api.addFeed(f); ok++ } catch { /* keep going */ } }
    return { msg: `${ok} of ${STARTER_FEEDS.length} feeds added and polled` }
  }, 'Adding feeds…')

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
          <div className="sig-chan-v">{liveFeeds.length || 'None'} {liveFeeds.length === 1 ? 'feed' : 'feeds'}</div>
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
              onAddStarters={addStarters} onReload={load} onNote={setNote} />
          )}
          {view === 'backlog' && <Backlog rows={backlog} onReload={load} />}
          {view === 'feeds' && <Feeds rows={feeds} onReload={load} onNote={setNote} />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

// --- queue -------------------------------------------------------------------

function Queue({ people, topics, feeds, busy, onAddStarters, onReload, onNote }) {
  const [adding, setAdding] = useState(false)

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
          <h4 className="sig-h sig-h-quiet">Topics moving <span className="sig-h-n">{topics.length}</span></h4>
          <p className="sig-h-sub">Nobody is waiting on these. Useful for what to post about, not who to talk to.</p>
          <div className="sig-topics">
            {topics.map((s) => <TopicRow key={s.id} s={s} onReload={onReload} />)}
          </div>
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

function Feeds({ rows, onReload, onNote }) {
  const [f, setF] = useState({ url: '', name: '', keywords: '' })
  const [busy, setBusy] = useState(false)
  const add = async () => {
    if (!f.url.trim()) return
    setBusy(true)
    try {
      const r = await api.addFeed({ url: f.url.trim(), name: f.name.trim(), keywords: f.keywords.split(',').map((s) => s.trim()).filter(Boolean) })
      onNote(`Added — ${r.new} item${r.new === 1 ? '' : 's'} on the first read`)
      setF({ url: '', name: '', keywords: '' }); onReload()
    } catch (e) { onNote(String(e.message || e).slice(0, 200)) }
    finally { setBusy(false) }
  }

  return (
    <div>
      <p className="sig-h-sub sig-backlog-lede">
        A publisher hosts a feed on purpose, so polling one is reading what was published for reading.
        For a Google Alert, set <b>Deliver to → RSS feed</b> and paste the URL it gives you.
        Keywords are optional — leave them blank to keep everything.
      </p>
      <div className="sig-add-row sig-feed-form">
        <input className="field-input" placeholder="Feed URL" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
        <input className="field-input" placeholder="Name it" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <input className="field-input" placeholder="Keywords, comma separated" value={f.keywords} onChange={(e) => setF({ ...f, keywords: e.target.value })} />
        <button className="btn primary" onClick={add} disabled={busy}>{busy ? 'Checking…' : 'Add feed'}</button>
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
                  {r.keywords?.length > 0 && <> · filtered on <b>{r.keywords.join(', ')}</b></>}
                  {r.last_poll && <> · checked {ago(r.last_poll)}{r.last_note ? ` — ${r.last_note}` : ''}</>}
                </div>
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
