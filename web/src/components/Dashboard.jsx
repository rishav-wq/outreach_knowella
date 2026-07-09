import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import AnimatedNumber from './AnimatedNumber'
import Skeleton from './Skeleton'
import { fadeUp, stagger, tap } from './anim'

// Overview is a WORK QUEUE, not a stats poster: the hero is the single next
// action, the pipeline is a compact rail underneath, and outcome numbers
// support the decision instead of leading the page.
const RANK = { new: 0, invalid: 0, error: 0, rejected: 0, suppressed: 0, bounced: 4, researched: 1, gated: 2, drafted: 2, dropped: 2, queued: 3, held: 3, sent: 4 }
const RAIL = [['Leads', 0], ['Researched', 1], ['Drafted', 2], ['Awaiting review', 3], ['Sent', 4]]
const ATTENTION = [['rejected', 'rejected'], ['invalid', 'invalid email'], ['dropped', 'dropped'], ['suppressed', 'do-not-contact'], ['bounced', 'bounced'], ['error', 'errors']]

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
      load() // keep the rail moving while the pipeline works
      if (!s.running) {
        clearInterval(poll.current)
        setRunning(false)
        setMsg(s.error ? 'Pipeline stopped with an error: ' + s.error : 'Pipeline finished. New drafts are waiting on the Review tab.')
      }
    }, 2000)
  }

  useEffect(() => {
    setLoading(true); setDelivery(null); setAb(null); setRunning(false); load()
    api.getAnalytics(campaign)
      .then((d) => setDelivery(d.connected || d.outcomes?.replies || d.outcomes?.sent ? d : null))
      .catch(() => {})
    api.getAB(campaign).then((d) => setAb(Object.keys(d.variants || {}).length > 1 ? d : null)).catch(() => {})
    // reconnect to a run started earlier (e.g. before you navigated away)
    api.getRunStatus(campaign).then((s) => { if (s.running) { setRunning(true); beginPolling() } }).catch(() => {})
    return () => clearInterval(poll.current)
  }, [campaign])

  const startRun = async () => {
    const lim = runLimit || null   // 0 = all
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
  const railCount = (minRank) =>
    Object.entries(c).reduce((sum, [s, n]) => sum + ((RANK[s] ?? 0) >= minRank ? n : 0), 0)

  // The single most useful thing to do next, given where the campaign stands.
  const nextStep = () => {
    if (running) return { title: 'Pipeline is running', sub: 'Each lead is being researched against real sources and drafted. Drafts land on Review as they finish.', cta: null }
    if (queued > 0) return { title: `${queued} ${queued === 1 ? 'draft waits' : 'drafts wait'} for your sign-off`, sub: 'Read each draft and its verified sources, then approve the ones worth sending. Nothing sends without you.', cta: 'Review drafts', go: 'Review' }
    if (newCount > 0) return { title: `${newCount} ${newCount === 1 ? 'lead is' : 'leads are'} ready to research`, sub: 'Run the pipeline to research each lead and draft a grounded email for your review.', cta: 'Run pipeline', go: 'run' }
    if (sent > 0) return { title: 'All clear — watch for replies', sub: 'Everything reviewed and sent. Replies land in the Inbox, classified as they arrive.', cta: 'Open Inbox', go: 'Inbox' }
    return { title: 'Start by adding leads', sub: 'Pull a filtered list straight from Apollo, or import a CSV.', cta: 'Add leads', go: 'Leads' }
  }
  const step = nextStep()

  if (loading) {
    return (
      <div>
        <Skeleton h={150} r={10} />
        <Skeleton h={80} r={10} style={{ marginTop: 18 }} />
        <Skeleton w="38%" h={14} style={{ marginTop: 18 }} />
      </div>
    )
  }

  if (total === 0 && !running) {
    return (
      <motion.div className="empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
        <div className="empty-icon"><Icon name="users" size={24} /></div>
        <h3>This campaign has no leads yet</h3>
        <p className="muted">Pull a filtered list from Apollo (or import a CSV) on the Leads tab. Then run the pipeline here to research each one and draft an email for your review.</p>
        <div className="empty-actions">
          <button className="btn primary" onClick={() => onNavigate('Leads')}><Icon name="users" size={15} /> Add leads</button>
        </div>
      </motion.div>
    )
  }

  return (
    <div>
      {msg && <motion.div className="banner" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}>{msg}</motion.div>}

      {/* HERO — the next action, not a vanity number */}
      <motion.section className="work-hero" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <div className="wh-eyebrow">Next action · {campaign}</div>
        <h2 className="wh-title">{step.title}</h2>
        <p className="wh-sub">{step.sub}</p>
        <div className="wh-actions">
          {running ? (
            <span className="wh-running"><span className="spinner" /> researching &amp; drafting…</span>
          ) : (
            <>
              {step.cta && step.go !== 'run' && (
                <motion.button className="btn primary" onClick={() => onNavigate(step.go)} {...tap}>{step.cta}</motion.button>
              )}
              {step.go === 'run' && (
                <motion.button className="btn primary" onClick={startRun} {...tap}><Icon name="play" size={15} /> Run pipeline</motion.button>
              )}
              <span className="wh-secondary">
                {step.go !== 'run' && newCount > 0 && (
                  <button className="btn" disabled={running} onClick={startRun}><Icon name="play" size={14} /> Run pipeline</button>
                )}
                <select className="src-select" value={runLimit} onChange={(e) => setRunLimit(Number(e.target.value))} disabled={running} title="How many unprocessed leads to research + draft this run">
                  <option value={25}>25 leads</option>
                  <option value={50}>50 leads</option>
                  <option value={100}>100 leads</option>
                  <option value={0}>All leads</option>
                </select>
                <button className="btn" onClick={() => onNavigate('Leads')}><Icon name="users" size={14} /> Add leads</button>
              </span>
            </>
          )}
        </div>
      </motion.section>

      {/* PIPELINE RAIL — the lifecycle as a ledger line, not stat cards */}
      <motion.div className="rail" variants={stagger} initial="hidden" animate="show">
        {RAIL.map(([label, rank], i) => {
          const n = railCount(rank)
          return (
            <motion.div className={`rail-stage ${n ? 'on' : ''} ${rank === 4 && n ? 'done' : ''}`} key={label} variants={fadeUp}>
              <span className="rail-tick" />
              <span className="rail-num"><AnimatedNumber value={n} /></span>
              <span className="rail-label">{label}</span>
              {i < RAIL.length - 1 && <span className="rail-link" />}
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

      {delivery?.outcomes && (delivery.outcomes.sent > 0 || delivery.outcomes.replies > 0) && (
        <>
          <div className="section-label">Outcomes · what actually matters</div>
          <motion.div className="funnel delivery" variants={stagger} initial="hidden" animate="show">
            {[
              ['Positive replies', delivery.outcomes.positive, delivery.outcomes.sent ? `${delivery.outcomes.positive_rate}%` : ''],
              ['Meetings booked', delivery.outcomes.meetings, ''],
              ['Not interested', delivery.outcomes.by_label?.not_interested || 0, ''],
              ['Opted out', delivery.outcomes.by_label?.opt_out || 0, ''],
            ].map(([label, n, rate]) => (
              <motion.div className={`stage ${n ? 'on' : ''} ${label === 'Positive replies' && n ? 'done' : ''}`} key={label} variants={fadeUp}>
                <div className="stage-num"><AnimatedNumber value={n || 0} />{rate && <span className="stage-rate">{rate}</span>}</div>
                <div className="stage-label">{label}</div>
              </motion.div>
            ))}
          </motion.div>
        </>
      )}

      {delivery?.connected && (
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
                  <div className="ab-rate"><AnimatedNumber value={s.positive_rate ?? s.reply_rate} />%</div>
                  <div className="ab-label">{v === 'signal' ? 'signal-led opener' : 'plain control'}</div>
                  <div className="ab-sub">{s.interested ?? 0} interested · {s.replied}/{s.sent || s.drafted} replied</div>
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
