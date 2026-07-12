import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import * as api from '../api'
import Skeleton from './Skeleton'
import Drawer from './Drawer'
import { fadeUp, stagger } from './anim'

const COLUMNS = ['New', 'Drafted', 'Review', 'Approved', 'Sent', 'Skipped']

function columnFor(c) {
  const s = c.status, d = c.decision
  if (s === 'sent') return 'Sent'
  if (s === 'rejected' || s === 'invalid' || s === 'dropped' || s === 'error' || d === 'rejected') return 'Skipped'
  if (s === 'queued') return d === 'approved' ? 'Approved' : 'Review'
  if (s === 'researched' || s === 'drafted' || s === 'gated') return 'Drafted'
  return 'New'
}

// `embedded` = rendered as the Board view inside Review, whose header already
// owns the Send action — so we hide our own send block to avoid two of them.
export default function Kanban({ campaign, embedded = false }) {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [sel, setSel] = useState(null)
  const [sourceFilter, setSourceFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [sendable, setSendable] = useState(false)
  const [sending, setSending] = useState(false)
  const [guard, setGuard] = useState(null)

  const load = () => api.getBoard(campaign).then(setCards).catch(() => setCards([])).finally(() => setLoading(false))
  useEffect(() => {
    setLoading(true); load()
    api.getStatus(campaign).then((s) => { setSendable(!!s.sendable); setGuard(s.guardrails || null) }).catch(() => {})
  }, [campaign])

  const guardLabel = () => {
    if (!guard) return ''
    const parts = []
    if (guard.daily_cap > 0) parts.push(`sent today ${guard.sent_today}/${guard.daily_cap}`)
    const w = guard.window || {}
    if (w.start_hour != null && w.end_hour != null) {
      parts.push(`window ${String(w.start_hour).padStart(2, '0')}–${String(w.end_hour).padStart(2, '0')}${w.weekdays_only ? ' weekdays' : ''}`)
    }
    return parts.join(' · ')
  }

  const sources = Array.from(new Set(cards.map((c) => c.source).filter(Boolean)))
  const q = query.trim().toLowerCase()
  const shown = cards
    .filter((c) => sourceFilter === 'all' || (c.source || '') === sourceFilter)
    .filter((c) => !q || `${c.name} ${c.company}`.toLowerCase().includes(q))
  const approvedCount = cards.filter((c) => c.decision === 'approved' && c.status === 'queued').length

  // After approving or rejecting, jump straight to the next draft waiting
  // for review so a batch can be worked through without extra clicks.
  const advanceFrom = (key) => {
    const reviewKeys = shown.filter((c) => columnFor(c) === 'Review').map((c) => c.key)
    const i = reviewKeys.indexOf(key)
    const next = reviewKeys.find((k, j) => j > i) || reviewKeys.find((k) => k !== key)
    setSel(next || null)
  }

  const sendApproved = async () => {
    if (!window.confirm(`Send ${approvedCount} approved ${approvedCount === 1 ? 'email' : 'emails'} through Apollo? This is the real send.`)) return
    setSending(true)
    const r = await api.runPipeline(campaign, true)
    if (!r.started) { setSending(false); return }
    const poll = setInterval(async () => {
      const s = await api.getRunStatus(campaign)
      if (!s.running) { clearInterval(poll); setSending(false); load() }
    }, 2000)
  }

  if (loading) {
    return (
      <div className="board">
        {COLUMNS.map((c) => (
          <div className="kcol" key={c}>
            <div className="kcol-head">{c}</div>
            <div className="kcol-body">
              {[0, 1].map((i) => (
                <div className="kcard" key={i}><Skeleton w="70%" h={13} /><Skeleton w="50%" h={11} style={{ marginTop: 8 }} /></div>
              ))}
            </div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div>
      <div className="board-bar">
        <div className="filters">
          <input className="search" type="search" placeholder="Search name or company" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            <option value="all">All sources</option>
            {sources.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <span className="count">{shown.length} {shown.length === 1 ? 'lead' : 'leads'}</span>
        </div>
        {!embedded && (
          <div className="board-send">
            {guardLabel() && <span className="guard-note" title="Deliverability guardrails from the campaign config">{guardLabel()}</span>}
            <button className="btn primary" disabled={!sendable || !approvedCount || sending}
              title={!sendable ? 'Connect Apollo (sequence + mailbox) to enable sending' : ''} onClick={sendApproved}>
              {sending ? <><span className="spinner" /> Sending…</> : `Send ${approvedCount} approved`}
            </button>
          </div>
        )}
      </div>

      <div className="board">
        {COLUMNS.map((col) => {
          const items = shown.filter((c) => columnFor(c) === col)
          return (
            <div className={`kcol k-${col.toLowerCase()}`} key={col}>
              <div className="kcol-head"><span className="kdot" /> {col} <span className="kcount">{items.length}</span></div>
              <motion.div className="kcol-body" variants={stagger} initial="hidden" animate="show">
                {items.map((c) => (
                  <motion.button key={c.key} variants={fadeUp} className="kcard" onClick={() => setSel(c.key)}>
                    <div className="kcard-name">{c.name}</div>
                    <div className="kcard-co">{c.company}</div>
                    {(c.source || c.decision) && (
                      <div className="kcard-tags">
                        {c.source && <span className="src-tag">{c.source}</span>}
                        {c.decision && <span className={`badge s-${c.decision}`}>{c.decision}</span>}
                      </div>
                    )}
                  </motion.button>
                ))}
                {items.length === 0 && <div className="kcol-empty">Empty</div>}
              </motion.div>
            </div>
          )
        })}
      </div>

      <AnimatePresence>
        {sel && (
          <Drawer key={sel} campaign={campaign} leadKey={sel} onClose={() => setSel(null)}
            onChange={load} onDecided={advanceFrom} />
        )}
      </AnimatePresence>
    </div>
  )
}
