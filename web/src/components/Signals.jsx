import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'
import SourceFlow from './SourceFlow'

// The listening post — three registers, in the order they deserve attention.
//
//   1. Someone asked   a named person, in public, waiting for a reply
//   2. Just cited      a named employer with a public compliance problem
//   3. Being talked about   a page mentioning our category; nobody to email
//
// The order is the argument. The first two are people and companies you can
// contact; the third is awareness. Mixing them is what made the earlier version
// useless — thirty-eight articles buried the one lead sitting underneath them.

const PERSON_KINDS = new Set(['question', 'comment', 'review', 'mention', 'reaction'])
const PLATFORM = {
  linkedin: 'LinkedIn', g2: 'G2', capterra: 'Capterra', trustpilot: 'Trustpilot',
  google_alert: 'Google Alert', rss: 'Feed', other: 'Other',
}

const ago = (iso) => {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 3600) return `${Math.floor(s / 60) || 1}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export default function Signals() {
  const [data, setData] = useState(null)
  const [backlog, setBacklog] = useState([])
  const [view, setView] = useState('queue')
  const [route, setRoute] = useState(null)   // sources -> campaigns board
  const [flow, setFlow] = useState('')       // selected source|campaign edge
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')

  const load = () => Promise.all([
    // Only the open queue: dismissed signals are kept for dedupe, never displayed,
    // and shipping them to the browser just to filter them out wastes the payload.
    api.listSignals('new').then(setData).catch(() => setData({ signals: [], counts: {} })),
    api.listBacklog().then(setBacklog).catch(() => setBacklog([])),
    api.getRouting().then(setRoute).catch(() => setRoute(null)),
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
    return { msg: r.citations ? `${r.citations} new citation${r.citations === 1 ? '' : 's'}` : 'No new citations' }
  }, 'Checking…')

  const clearTalk = () => act(async () => {
    const r = await api.clearSignals('email_mention')
    return { msg: `Cleared ${r.cleared} mention${r.cleared === 1 ? '' : 's'}` }
  }, 'Clearing…')

  const open = (data?.signals || []).filter((s) => s.status === 'new')
  // A person is someone with a name on the signal, or anything logged by hand —
  // a Google Alert hit is a page, however relevant, and belongs in the third bucket.
  const isPerson = (s) => PERSON_KINDS.has(s.kind) && (s.person || s.channel === 'manual')
  const people = useMemo(() => open.filter(isPerson), [data])
  const cited = useMemo(() => open.filter((s) => s.kind === 'citation'), [data])
  const talk = useMemo(() => open.filter((s) => !isPerson(s) && s.kind !== 'citation'), [data])
  // Which campaign each citation routes to — computed once here so the Queue table
  // can show it as a column instead of the Routing tab repeating the whole list.
  const citedRouted = useMemo(() => {
    const fit = {}
    for (const f of route?.flows || []) for (const i of f.items) fit[i.id] = f.campaign
    return cited.map((c) => ({ ...c, campaign_fit: fit[c.id] || '' }))
  }, [cited, route])
  const actionable = people.length + cited.length

  if (data === null) return <div><Skeleton h={44} /><Skeleton h={54} r={10} style={{ marginTop: 16 }} /><Skeleton h={260} r={12} style={{ marginTop: 14 }} /></div>

  return (
    <div className="sig">
      <div className="lib-head">
        <div>
          <div className="dash-eyebrow">Signals</div>
          <div className="lib-title">
            {actionable} <small>{actionable === 1 ? 'waiting on you' : 'waiting on you'}</small>
            {talk.length > 0 && <span className="sig-title-sub">· {talk.length} mentions</span>}
          </div>
        </div>
        <div className="dash-actions">
          <button className="btn" onClick={poll} disabled={!!busy}>
            <Icon name="download" size={14} /> {busy === 'Checking…' ? 'Checking…' : 'Check OSHA now'}
          </button>
        </div>
      </div>

      {/* One line, not three cards. It says only what you can't see from the list:
          whether the inbound address is actually receiving. */}
      <div className={`sig-bar-status ${data.inbound_ready ? 'on' : ''}`}>
        <span className="sig-dot" />
        {data.inbound_ready ? (
          <span><b>Receiving mail.</b> Forward LinkedIn, G2, Trustpilot, Google Alerts and F5Bot
            notifications to the inbound address and they land here.</span>
        ) : (
          <span><b>Notification email isn’t wired up</b> — the half that names real people. Set
            <code> SIGNALS_WEBHOOK_TOKEN</code> and point a Postmark inbound address at
            <code> /api/signals/inbound</code>.</span>
        )}
      </div>

      {note && <div className="banner">{note}</div>}

      <div className="seg sig-seg" role="tablist">
        {[['queue', `Queue${actionable ? ` (${actionable})` : ''}`],
          ['routing', `Routing${route?.flows?.length ? ` (${route.campaigns.reduce((a, c) => a + c.ready, 0)})` : ''}`],
          ['backlog', `Backlog${backlog.length ? ` (${backlog.length})` : ''}`]].map(([k, label]) => (
          <button key={k} role="tab" aria-selected={view === k} className={view === k ? 'on' : ''} onClick={() => setView(k)}>{label}</button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div key={view} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
          {view === 'queue' && (
            <Queue people={people} cited={citedRouted} talk={talk} busy={busy}
              inboundReady={data.inbound_ready} onClearTalk={clearTalk}
              onReload={load} onNote={setNote} />
          )}
          {view === 'routing' && (
            <RoutingView cited={citedRouted} route={route} flow={flow}
              setFlow={setFlow} onReload={load} onNote={setNote} />
          )}
          {view === 'backlog' && <Backlog rows={backlog} onReload={load} />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

// --- queue -------------------------------------------------------------------

function Queue({ people, cited, talk, busy, inboundReady, onClearTalk, onReload, onNote }) {
  const [adding, setAdding] = useState(false)
  const [allTalk, setAllTalk] = useState(false)

  if (!cited.length && !people.length && !talk.length && !inboundReady) {
    return (
      <>
        {adding && <AddByHand onDone={() => { setAdding(false); onReload() }} onCancel={() => setAdding(false)} />}
        <motion.div className="empty sig-empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <div className="empty-icon"><Icon name="inbox" size={24} /></div>
          <h3>Nothing waiting</h3>
          <p className="muted">
            {inboundReady
              ? 'Nothing has come in since you last cleared this. Citations are checked every 30 minutes.'
              : 'Forward your notification mail to the inbound address and this fills with people who asked something.'}
          </p>
          <div className="empty-actions">
            <button className="btn primary" onClick={() => setAdding(true)}>
              <Icon name="plus" size={14} /> Log what you saw
            </button>
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

      <section className="sig-sect">
        <h4 className={`sig-h ${people.length ? '' : 'sig-h-quiet'}`}>
          Someone asked <span className="sig-h-n">{people.length}</span>
        </h4>
        <p className="sig-h-sub">A named person, in public, waiting for an answer.</p>
        {people.length > 0 ? (
          <div className="sig-cards">
            {people.map((s) => <PersonCard key={s.id} s={s} onReload={onReload} onNote={onNote} />)}
          </div>
        ) : (
          <Dormant ready={inboundReady}
            arrives="LinkedIn comments and mentions, G2 and Capterra buyer questions, Trustpilot reviews"
            manual />
        )}
      </section>

      {cited.length > 0 && (
        <section className="sig-sect">
          <CitationTable rows={cited} onReload={onReload} onNote={onNote} />
        </section>
      )}

      {talk.length === 0 && (
        <section className="sig-sect">
          <h4 className="sig-h sig-h-quiet">Being talked about <span className="sig-h-n">0</span></h4>
          <p className="sig-h-sub">Pages mentioning our category. Awareness, and post material.</p>
          <Dormant ready={inboundReady} arrives="Google Alerts (set to email delivery) and F5Bot digests" />
        </section>
      )}

      {talk.length > 0 && (
        <section className="sig-sect">
          <h4 className="sig-h sig-h-quiet">
            Being talked about <span className="sig-h-n">{talk.length}</span>
            <button className="btn ghost sig-h-act" onClick={onClearTalk} disabled={!!busy}>Clear all</button>
          </h4>
          <p className="sig-h-sub">
            Pages mentioning our category. Nobody to email — this is awareness, and post material.
          </p>
          <div className="sig-topics">
            {(allTalk ? talk : talk.slice(0, 12)).map((s) => <TopicRow key={s.id} s={s} onReload={onReload} />)}
          </div>
          {talk.length > 12 && (
            <button className="btn sig-more" onClick={() => setAllTalk(!allTalk)}>
              {allTalk ? 'Show fewer' : `Show all ${talk.length}`}
            </button>
          )}
        </section>
      )}
    </>
  )
}

// An empty register that renders nothing looks like a register that doesn't exist.
// Four OSHA citations on screen read as "OSHA is all this does" unless the other two
// say out loud that they're waiting on a mailbox nobody has created yet.
function Dormant({ ready, arrives, manual }) {
  return (
    <div className="sig-dormant">
      <span className={`dot ${ready ? 'd-ok' : 'd-held'}`} />
      <div>
        {ready
          ? <><b>Nothing yet.</b> {arrives} land here.</>
          : <><b>Waiting on the inbound address.</b> {arrives} land here once notification mail is
              forwarded to it.</>}
        {manual && <> Anything you see in a group with no webhook goes in with <b>Add by hand</b>.</>}
      </div>
    </div>
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

// The map answers a question the list can't: where is enforcement landing? At a
// handful of citations that's a curiosity; against the full DOL inspection dataset
// it becomes a territory picker. Built so it works either way.
function RoutingView({ cited, route, flow, setFlow, onReload, onNote }) {
  if (!cited.length) {
    return (
      <div className="empty">
        <div className="empty-icon"><Icon name="download" size={24} /></div>
        <h3>Nothing waiting to be routed</h3>
        <p className="muted">
          This is where cited employers queue up against the campaign they fit.
          Hit <b>Check OSHA now</b> to look for new ones.
        </p>
      </div>
    )
  }
  const picked = route?.flows?.find((f) => `${f.source_id}|${f.campaign}` === flow)
  const shown = picked ? cited.filter((c) => picked.items.some((i) => i.id === c.id)) : []

  return (
    <>
      {route && route.flows.length > 0 && (
        <SourceFlow data={route} selected={flow} onSelect={setFlow} />
      )}

      {/* Only what you asked to see. The full list is one tab away on Queue, and
          printing it here as well is how the page ended up saying everything twice. */}
      {picked ? (
        <div style={{ marginTop: 24 }}>
          <h4 className="sig-h">
            {picked.source} → {picked.campaign || 'unrouted'}
            <span className="sig-h-n sig-h-n-hot">{shown.length}</span>
          </h4>
          <div style={{ marginTop: 12 }}>
            <CitationTable rows={shown} hideHeading onReload={onReload} onNote={onNote} />
          </div>
        </div>
      ) : (
        <p className="sig-h-sub" style={{ marginTop: 18 }}>
          Click a route above to see which employers it covers. The full list, with fit and
          the add flow, is on <b>Queue</b>.
        </p>
      )}
    </>
  )
}


// Citations, as a dashboard rather than a stack of cards.
//
// Reading the first four releases in full showed the ranking was backwards: the
// $700K double-fatality gas release is the worst lead on the list and the $264K
// confined-space case is the best. Penalty measures how bad the harm was, not
// whether the employer will buy anything — so fit leads, penalty is a column, and
// poor-fit rows are folded away rather than competing for attention.
const FIT_ORDER = { good: 0, fair: 1, poor: 2 }
const VIOL_ORDER = ['willful', 'repeat', 'serious', 'other-than-serious']

function violText(v) {
  if (!v) return '—'
  const parts = VIOL_ORDER.filter((k) => v[k]).map((k) => `${v[k]} ${k}`)
  return parts.length ? parts.join(', ') : '—'
}

function CitationTable({ rows, hideHeading, onReload, onNote }) {
  const [open, setOpen] = useState('')
  const [showPoor, setShowPoor] = useState(false)
  const sorted = [...rows].sort((a, b) => (FIT_ORDER[a.fit] ?? 1) - (FIT_ORDER[b.fit] ?? 1))
  const poor = sorted.filter((r) => r.fit === 'poor')
  const shown = showPoor ? sorted : sorted.filter((r) => r.fit !== 'poor')

  return (
    <>
      <h4 className="sig-h">
        Just cited by OSHA <span className="sig-h-n sig-h-n-hot">{sorted.length - poor.length}</span>
      </h4>
      <p className="sig-h-sub">
        Ranked by whether they'll buy, not by penalty. A company cited for <b>serious</b> violations
        had a gap; one cited for <b>willful</b> or <b>repeat</b> decided — and software doesn't fix intent.
      </p>
      <div className="cit">
        <div className="cit-head">
          <span>Employer</span><span>Where</span><span>Violations</span>
          <span>Penalty</span><span>Campaign</span><span>Fit</span><span />
        </div>
        {shown.map((r) => (
          <div key={r.id} className={`cit-row f-${r.fit} ${open === r.id ? 'is-open' : ''}`}>
            <button className="cit-line" onClick={() => setOpen(open === r.id ? '' : r.id)}>
              <span className="cit-co">{r.company || r.title}</span>
              <span className="cit-mut">{r.location || '—'}</span>
              <span className="cit-mut">{violText(r.violations)}</span>
              <span className="cit-pen">${Number(r.penalty || 0).toLocaleString()}</span>
              <span className={`cit-camp ${r.campaign_fit ? '' : 'none'}`}>
                {r.campaign_fit || 'unrouted'}
              </span>
              <span className={`cit-fit f-${r.fit}`} title={r.fit_why}>{r.fit}</span>
              <span className="cit-chev">{open === r.id ? '⌃' : '⌄'}</span>
            </button>
            {open === r.id && (
              <div className="cit-detail">
                <p className="cit-why"><b>{r.fit_why}</b>{r.priors > 0 && <> · inspected {r.priors} times before</>}</p>
                {r.text && <p className="sig-card-text">{r.text}</p>}
                <CitationActions s={r} onReload={onReload} onNote={onNote} />
              </div>
            )}
          </div>
        ))}
      </div>
      {poor.length > 0 && (
        <button className="cit-more" onClick={() => setShowPoor(!showPoor)}>
          {showPoor ? 'Hide' : `Show ${poor.length} poor fit`} — willful or repeat offenders, not prospects
        </button>
      )}
    </>
  )
}

function CitationActions({ s, onReload, onNote }) {
  const [cands, setCands] = useState(null)
  const [busy, setBusy] = useState('')
  const [campaigns, setCampaigns] = useState([])
  const [campaign, setCampaign] = useState('')
  const [done, setDone] = useState(null)

  const resolve = async () => {
    setBusy('look')
    try {
      const [r, cs] = await Promise.all([api.resolveCitation(s.id), api.getCampaigns()])
      setCands(r.candidates || []); setCampaigns(cs)
      setCampaign(s.campaign_fit && cs.includes(s.campaign_fit) ? s.campaign_fit : cs[0] || '')
    } catch (e) { onNote(String(e.message || e).slice(0, 180)) }
    finally { setBusy('') }
  }
  const [picked, setPicked] = useState({})     // org id -> Set of person ids
  const toggle = (orgId, pid) => setPicked((p) => {
    const cur = new Set(p[orgId] || [])
    cur.has(pid) ? cur.delete(pid) : cur.add(pid)
    return { ...p, [orgId]: cur }
  })
  const chosen = (o) => {
    const set = picked[o.id]
    // Default to the single best-ranked contact. One email to the right person beats
    // three to the same company, which is what a blast looks like from the inside.
    return set ? [...set] : (o.contacts[0] ? [o.contacts[0].id] : [])
  }
  const add = async (org) => {
    setBusy(org.id)
    try {
      const r = await api.promoteCitation(s.id, org.id, campaign, chosen(org))
      setDone(r); onReload()
      onNote(`${r.added} added to ${r.campaign} — ${r.credits} credit${r.credits === 1 ? '' : 's'}`)
    } catch (e) { onNote(String(e.message || e).slice(0, 200)) }
    finally { setBusy('') }
  }

  if (done) return <div className="pin-done">✓ Added {done.added} to <b>{done.campaign}</b></div>
  if (cands === null) {
    return (
      <div className="cit-act">
        <button className="btn primary" onClick={resolve} disabled={!!busy}>
          {busy ? 'Looking up…' : 'Find who to contact'}
        </button>
        <a className="btn" href={s.url} target="_blank" rel="noreferrer">Read the release ↗</a>
        <span className="cit-free">Looking up is free — credits are only spent when you add someone</span>
      </div>
    )
  }
  const usable = cands.filter((o) => o.contacts.length)
  const skipped = cands.filter((o) => !o.checked).length
  if (!usable.length) {
    return <div className="pin-none">Apollo has no reachable contact at <b>{s.company}</b>. Small
      contractors often aren't in it at all.</div>
  }
  return (
    <div className="cit-pick">
      <div className="sig-cite-pick-h">
        Who should hear about it? <span className="muted">One person, usually — three colleagues
        getting the same email reads as a blast. 1 Apollo credit each.</span>
        <select className="field-input" value={campaign} onChange={(e) => setCampaign(e.target.value)}>
          {campaigns.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      {usable.map((o) => {
        const sel = chosen(o)
        return (
          <div key={o.id} className="cit-org">
            <div className="cit-org-h">
              <b>{o.name}</b> <span className="sig-dom">{o.domain}</span>
              <button className="btn primary" disabled={!!busy || !campaign || !sel.length}
                onClick={() => add(o)}>
                {busy === o.id ? 'Adding…' : `Add ${sel.length}`}
              </button>
            </div>
            <ul className="cit-people">
              {o.contacts.map((p) => (
                <li key={p.id}>
                  <label>
                    <input type="checkbox" checked={sel.includes(p.id)} onChange={() => toggle(o.id, p.id)} />
                    <span className="cit-p-name">{p.first_name}</span>
                    <span className="cit-p-title">{p.title}</span>
                    <span className="cit-p-why" title="Why this ranking">{p.why}</span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
      {skipped > 0 && (
        <p className="cit-free">
          {skipped} other name {skipped === 1 ? 'match' : 'matches'} had no domain, so {skipped === 1 ? 'it wasn’t' : 'they weren’t'} looked
          up — Apollo matches loosely and those are usually duplicates or unrelated businesses.
        </p>
      )}
    </div>
  )
}


function TopicRow({ s, onReload }) {
  return (
    <motion.div layout className="sig-topic" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <span className="sig-topic-src">{s.topic || PLATFORM[s.platform] || s.platform}</span>
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

