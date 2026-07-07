import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import AnimatedNumber from './AnimatedNumber'
import Skeleton from './Skeleton'
import { fadeUp, stagger, tap } from './anim'

const RANK = { new: 0, invalid: 0, error: 0, rejected: 0, researched: 1, gated: 2, drafted: 2, dropped: 2, queued: 3, held: 3, sent: 4 }
const FUNNEL = [['Leads', 0], ['Researched', 1], ['Drafted', 2], ['Queued', 3], ['Sent', 4]]
const ATTENTION = [['rejected', 'rejected'], ['invalid', 'invalid email'], ['dropped', 'dropped'], ['error', 'errors']]

export default function Dashboard({ campaign, onNavigate }) {
  const [status, setStatus] = useState({ counts: {}, tokens: {} })
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [msg, setMsg] = useState('')
  const [delivery, setDelivery] = useState(null)
  const [ab, setAb] = useState(null)
  const [runLimit, setRunLimit] = useState(25)   // 0 = all; batches the expensive run
  const poll = useRef(null)

  const load = () => api.getStatus(campaign).then(setStatus).catch(() => {}).finally(() => setLoading(false))

  // The run lives on the backend; the browser only polls it. This lets any
  // mount (e.g. returning to Overview) reconnect to a run already in progress.
  const beginPolling = () => {
    clearInterval(poll.current)
    poll.current = setInterval(async () => {
      const s = await api.getRunStatus(campaign)
      load() // keep the funnel moving while the pipeline works
      if (!s.running) {
        clearInterval(poll.current)
        setRunning(false)
        setMsg(s.error ? 'Pipeline stopped with an error: ' + s.error : 'Pipeline finished. New drafts are waiting on the Review tab.')
      }
    }, 2000)
  }

  useEffect(() => {
    setLoading(true); setDelivery(null); setAb(null); setRunning(false); load()
    api.getAnalytics(campaign).then((d) => setDelivery(d.connected ? d : null)).catch(() => {})
    api.getAB(campaign).then((d) => setAb(Object.keys(d.variants || {}).length > 1 ? d : null)).catch(() => {})
    // reconnect to a run started earlier (e.g. before you navigated away)
    api.getRunStatus(campaign).then((s) => { if (s.running) { setRunning(true); beginPolling() } }).catch(() => {})
    return () => clearInterval(poll.current)
  }, [campaign])

  const startRun = async () => {
    const lim = runLimit || null   // 0 → all
    const newCount = (status.counts || {}).new || 0
    if (!lim && newCount > 50 &&
        !window.confirm(`Run the pipeline on all ${newCount} unprocessed leads? Each one is researched and drafted (LLM cost + a few minutes). Consider a smaller batch first.`)) return
    setMsg('')
    const r = await api.runPipeline(campaign, false, lim)
    if (!r.started) { setMsg(r.reason || 'The pipeline could not start.'); return }
    setRunning(true)
    beginPolling()
  }

  const c = status.counts || {}
  const total = Object.values(c).reduce((a, b) => a + b, 0)
  const queued = c.queued || 0
  const newCount = c.new || 0
  const sent = c.sent || 0
  const funnelCount = (minRank) =>
    Object.entries(c).reduce((sum, [s, n]) => sum + ((RANK[s] ?? 0) >= minRank ? n : 0), 0)

  // The single most useful thing to do next, given where the campaign stands.
  // Guides the whole lifecycle: add leads → run → review → send → watch replies.
  const nextStep = () => {
    if (running) return null
    if (queued > 0) return { title: `${queued} ${queued === 1 ? 'draft is' : 'drafts are'} waiting for your review`, sub: 'Read each draft and its sources, then approve the ones worth sending.', cta: 'Review drafts', go: 'Review' }
    if (newCount > 0) return { title: `${newCount} ${newCount === 1 ? 'lead is' : 'leads are'} ready to process`, sub: 'Run the pipeline to research each lead and draft a grounded email.', cta: 'Run pipeline', go: 'run' }
    if (sent > 0) return { title: 'All caught up — nothing to review', sub: 'Keep an eye on the Inbox for replies to the emails you sent.', cta: 'Open Inbox', go: 'Inbox' }
    return null
  }
  const step = nextStep()

  if (loading) {
    return (
      <div>
        <div className="dash-head">
          <div><Skeleton w={130} h={11} /><Skeleton w={220} h={36} style={{ marginTop: 10 }} /></div>
          <Skeleton w={150} h={36} r={7} />
        </div>
        <div className="funnel">
          {[0, 1, 2, 3, 4].map((i) => (
            <div className="stage" key={i}><Skeleton w="45%" h={30} /><Skeleton w="65%" h={10} style={{ marginTop: 12 }} /></div>
          ))}
        </div>
        <Skeleton h={60} r={10} style={{ marginBottom: 24 }} />
        <Skeleton w="38%" h={14} />
      </div>
    )
  }

  if (total === 0 && !running) {
    return (
      <motion.div className="empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
        <div className="empty-icon"><Icon name="users" size={24} /></div>
        <h3>This campaign has no leads yet</h3>
        <p className="muted">Add leads first — import a CSV on the Leads tab. Then run the pipeline here to research each one and draft an email for your review.</p>
        <div className="empty-actions">
          <button className="btn primary" onClick={() => onNavigate('Leads')}><Icon name="users" size={15} /> Add leads</button>
        </div>
      </motion.div>
    )
  }

  return (
    <div>
      <motion.div className="dash-head" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <div>
          <div className="dash-eyebrow">{campaign} · pipeline</div>
          <div className="dash-title"><AnimatedNumber value={total} /><small>leads</small></div>
          <div className="dash-sub">{queued} waiting for review · {c.sent || 0} sent · {c.new || 0} not yet processed</div>
        </div>
        <div className="dash-actions">
          <button className="btn" onClick={() => onNavigate('Leads')}><Icon name="users" size={15} /> Add leads</button>
          <select className="src-select" value={runLimit} onChange={(e) => setRunLimit(Number(e.target.value))} disabled={running} title="How many unprocessed leads to research + draft this run">
            <option value={25}>25 leads</option>
            <option value={50}>50 leads</option>
            <option value={100}>100 leads</option>
            <option value={0}>All leads</option>
          </select>
          <motion.button className="btn primary" disabled={running} onClick={startRun} {...(running ? {} : tap)}>
            {running ? <><span className="spinner" /> Running…</> : <><Icon name="play" size={15} /> Run pipeline</>}
          </motion.button>
        </div>
      </motion.div>

      {msg && <motion.div className="banner" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}>{msg}</motion.div>}

      {step && (
        <motion.button className="nudge" onClick={() => (step.go === 'run' ? startRun() : onNavigate(step.go))}
          initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} whileHover={{ scale: 1.005 }}>
          <div>
            <div className="nudge-eyebrow">Next step</div>
            <strong>{step.title}</strong>
            <div className="muted">{step.sub}</div>
          </div>
          <span className="btn primary">{step.cta}</span>
        </motion.button>
      )}

      <div className="section-label">Funnel</div>
      <motion.div className="funnel" variants={stagger} initial="hidden" animate="show">
        {FUNNEL.map(([label, rank]) => {
          const n = funnelCount(rank)
          const pct = total ? Math.round((n / total) * 100) : 0
          return (
            <motion.div className={`stage ${n ? 'on' : ''} ${rank === 4 && n ? 'done' : ''}`} key={label} variants={fadeUp}>
              <div className="stage-num"><AnimatedNumber value={n} /></div>
              <div className="stage-label">{label}</div>
              <div className="stage-bar"><i style={{ width: `${pct}%` }} /></div>
            </motion.div>
          )
        })}
      </motion.div>

      <motion.div className="attention" variants={stagger} initial="hidden" animate="show">
        {ATTENTION.map(([k, label]) => (
          <motion.div className="pill-stat" key={k} variants={fadeUp}>
            <span className={`dot d-${k}`} /> <b>{c[k] || 0}</b> {label}
          </motion.div>
        ))}
      </motion.div>

      {delivery && (
        <>
          <div className="section-label">Delivery · Apollo</div>
          <motion.div className="funnel delivery" variants={stagger} initial="hidden" animate="show">
            {[
              ['Sent', delivery.sent, ''],
              ['Opens', delivery.opens, delivery.sent ? `${Math.round((delivery.opens / delivery.sent) * 100)}%` : ''],
              ['Replies', delivery.replies, delivery.sent ? `${Math.round((delivery.replies / delivery.sent) * 100)}%` : ''],
              ['Clicks', delivery.clicks, delivery.sent ? `${Math.round((delivery.clicks / delivery.sent) * 100)}%` : ''],
              ['Bounced', delivery.bounced, delivery.sent ? `${Math.round((delivery.bounced / delivery.sent) * 100)}%` : ''],
            ].map(([label, n, rate]) => (
              <motion.div className={`stage ${n ? 'on' : ''}`} key={label} variants={fadeUp}>
                <div className="stage-num"><AnimatedNumber value={n || 0} />{rate && <span className="stage-rate">{rate}</span>}</div>
                <div className="stage-label">{label}</div>
              </motion.div>
            ))}
          </motion.div>
        </>
      )}

      {ab && (
        <>
          <div className="section-label">A/B · does the signal opener lift replies?</div>
          <motion.div className="ab-row" variants={stagger} initial="hidden" animate="show">
            {['signal', 'plain'].filter((v) => ab.variants[v]).map((v) => {
              const s = ab.variants[v]
              return (
                <motion.div className={`ab-cell ${v}`} key={v} variants={fadeUp}>
                  <div className="ab-rate"><AnimatedNumber value={s.reply_rate} />%</div>
                  <div className="ab-label">{v === 'signal' ? 'signal-led opener' : 'plain control'}</div>
                  <div className="ab-sub">{s.replied}/{s.sent || s.drafted} replied</div>
                </motion.div>
              )
            })}
          </motion.div>
        </>
      )}

      <div className="stats">
        <span><strong><AnimatedNumber value={total} /></strong> leads</span>
        <span><strong><AnimatedNumber value={status.tokens?.prompt_tokens || 0} /></strong> prompt tokens</span>
        <span><strong><AnimatedNumber value={status.tokens?.completion_tokens || 0} /></strong> completion tokens</span>
      </div>
    </div>
  )
}
