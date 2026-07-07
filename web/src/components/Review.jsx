import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'
import Kanban from './Kanban'

// The hero: a focused, one-lead-at-a-time review of AI drafts and their
// verified evidence — the mechanic that separates this product from the
// autonomous AI-SDR tools that shipped hallucinations. Draft on the left,
// the evidence it stands on to its right, keyboard-driven, auto-advancing.

const nextUndecided = (items, from) => {
  for (let j = from + 1; j < items.length; j++) if (!items[j].decision) return j
  for (let j = 0; j < items.length; j++) if (!items[j].decision) return j
  return from
}

export default function Review({ campaign }) {
  const [items, setItems] = useState(null)
  const [i, setI] = useState(0)
  const [view, setView] = useState('queue')       // 'queue' | 'board'
  const [editing, setEditing] = useState(false)
  const [eSubject, setESubject] = useState('')
  const [eBody, setEBody] = useState('')
  const [emailEdit, setEmailEdit] = useState(false)
  const [eEmail, setEEmail] = useState('')
  const [emailErr, setEmailErr] = useState('')
  const [sendable, setSendable] = useState(false)
  const [guard, setGuard] = useState(null)
  const [sending, setSending] = useState(false)
  const [sendFrom, setSendFrom] = useState('')
  const poll = useRef(null)

  const loadStatus = () =>
    api.getStatus(campaign).then((s) => { setSendable(!!s.sendable); setGuard(s.guardrails || null) }).catch(() => {})
  const load = () => api.getReview(campaign)
    .then((d) => { setItems(d); setI((prev) => Math.min(prev, Math.max(0, d.length - 1))) })
    .catch(() => setItems([]))

  useEffect(() => {
    setItems(null); setI(0); setEditing(false); setSendFrom('')
    load(); loadStatus()
    api.getMailboxes(campaign).then((d) => {
      const cur = (d.mailboxes || []).find((b) => b.id === d.current)
      setSendFrom(cur ? cur.email : '')
    }).catch(() => {})
    return () => clearInterval(poll.current)
  }, [campaign])

  const current = items && items[i]
  const total = items?.length || 0
  const decidedCount = items?.filter((it) => it.decision).length || 0
  const approvedCount = items?.filter((it) => it.decision === 'approved').length || 0
  const remaining = total - decidedCount

  const patch = (key, fields) => setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...fields } : it)))

  const decide = useCallback(async (decision) => {
    if (!current) return
    const key = current.key
    const val = decision === 'approve' ? 'approved' : 'rejected'
    patch(key, { decision: val })
    setEditing(false)
    setI((idx) => nextUndecided(items, idx))
    try { await api.decide(campaign, key, decision) } catch { load() }
  }, [current, items, campaign])

  const saveEdit = async () => {
    const key = current.key
    await api.editEmail(campaign, key, eSubject, eBody)
    patch(key, { subject: eSubject, body: eBody, edited: true })
    setEditing(false)
  }
  const startEdit = () => { setESubject(current.subject); setEBody(current.body); setEditing(true) }

  const saveEmail = async () => {
    setEmailErr('')
    try {
      const r = await api.setLeadEmail(campaign, current.key, eEmail)
      patch(current.key, { email: r.email, verify: r.verify })
      setEmailEdit(false)
    } catch (e) {
      setEmailErr(/valid email/.test(String(e.message)) ? 'That doesn’t look like a valid email address.' : `Could not save: ${e.message}`)
    }
  }

  // keyboard: j/k move, a approve, r reject, e edit — ignored while typing.
  useEffect(() => {
    const onKey = (e) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)
      if (view !== 'queue' || !current) return
      if (e.key === 'Escape' && editing) { setEditing(false); return }
      if (typing) return
      if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); setI((x) => Math.min(total - 1, x + 1)) }
      else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); setI((x) => Math.max(0, x - 1)) }
      else if (e.key === 'a' || e.key === 'A') { e.preventDefault(); decide('approve') }
      else if (e.key === 'r' || e.key === 'R') { e.preventDefault(); decide('reject') }
      else if (e.key === 'e' || e.key === 'E') { e.preventDefault(); if (current.subject) startEdit() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [view, current, total, editing, decide])

  useEffect(() => { setEditing(false); setEmailEdit(false); setEmailErr('') }, [i])

  const sendApproved = async () => {
    if (!window.confirm(`Send ${approvedCount} approved ${approvedCount === 1 ? 'email' : 'emails'} through Apollo? This is the real send.`)) return
    setSending(true)
    const r = await api.runPipeline(campaign, true)
    if (!r.started) { setSending(false); return }
    poll.current = setInterval(async () => {
      const s = await api.getRunStatus(campaign)
      if (!s.running) { clearInterval(poll.current); setSending(false); load(); loadStatus() }
    }, 2000)
  }

  const guardLabel = () => {
    if (!guard) return ''
    const parts = []
    if (guard.daily_cap > 0) parts.push(`${guard.sent_today}/${guard.daily_cap} sent today`)
    const w = guard.window || {}
    if (w.start_hour != null && w.end_hour != null) parts.push(`${String(w.start_hour).padStart(2, '0')}–${String(w.end_hour).padStart(2, '0')}${w.weekdays_only ? ' wkdys' : ''}`)
    return parts.join(' · ')
  }

  const readiness = (it) => {
    if (!it) return null
    if (!it.email) return { kind: 'warn', text: 'Won’t send — no email address' }
    if (it.require_deliverable && it.verify !== 'deliverable') return { kind: 'warn', text: `Held — needs a verified address (${it.verify || 'unchecked'})` }
    return { kind: 'ok', text: 'Ready to send' }
  }

  const header = (
    <div className="review-bar">
      <div className="review-progress">
        {total > 0 && (
          <>
            <div className="rp-track"><i style={{ width: `${Math.round((decidedCount / total) * 100)}%` }} /></div>
            <span className="rp-text">{decidedCount}/{total} reviewed · <b>{remaining} left</b></span>
          </>
        )}
      </div>
      <div className="review-tools">
        <div className="seg">
          <button className={view === 'queue' ? 'on' : ''} onClick={() => setView('queue')}><Icon name="list" size={14} /> Queue</button>
          <button className={view === 'board' ? 'on' : ''} onClick={() => setView('board')}><Icon name="columns" size={14} /> Board</button>
        </div>
        {sendFrom && <span className="guard-note" title="Approved emails send from this Apollo mailbox"><Icon name="inbox" size={12} /> {sendFrom}</span>}
        {guardLabel() && <span className="guard-note">{guardLabel()}</span>}
        <button className="btn primary" disabled={!sendable || !approvedCount || sending}
          title={!sendable ? 'Connect Apollo (sequence + mailbox) to enable sending' : ''} onClick={sendApproved}>
          {sending ? <><span className="spinner" /> Sending…</> : `Send ${approvedCount} approved`}
        </button>
      </div>
    </div>
  )

  if (items === null) {
    return (
      <div className="review">
        {header}
        <div className="review-work">
          <div className="rq-list">{[0, 1, 2].map((k) => <div className="rq-skel" key={k}><Skeleton w="70%" h={13} /><Skeleton w="90%" h={11} style={{ marginTop: 7 }} /></div>)}</div>
          <div className="rq-draft"><Skeleton w="50%" h={18} /><Skeleton w="100%" h={160} r={8} style={{ marginTop: 18 }} /></div>
          <div className="rq-evidence"><Skeleton w="60%" h={13} /><Skeleton w="100%" h={70} r={8} style={{ marginTop: 14 }} /></div>
        </div>
      </div>
    )
  }

  if (total === 0) {
    return (
      <div className="review">
        {header}
        <motion.div className="empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <div className="empty-icon"><Icon name="check" size={24} /></div>
          <h3>Nothing waiting for review</h3>
          <p className="muted">Run the pipeline from the Overview to research your leads and draft emails. Every draft lands here with its sources for you to approve.</p>
        </motion.div>
      </div>
    )
  }

  const ready = readiness(current)

  return (
    <div className="review">
      {header}
      {view === 'board' ? (
        <Kanban campaign={campaign} embedded />
      ) : (
        <div className="review-work">
          {/* queue rail */}
          <aside className="rq-list">
            {items.map((it, idx) => {
              const r = readiness(it)
              return (
                <button key={it.key} className={`rq-item ${idx === i ? 'on' : ''} ${it.decision || ''}`} onClick={() => setI(idx)}>
                  <div className="rq-mark">
                    {it.decision === 'approved' ? <Icon name="check" size={13} />
                      : it.decision === 'rejected' ? <Icon name="x" size={13} />
                      : <span className={`dot ${r.kind === 'ok' ? 'd-ok' : 'd-held'}`} />}
                  </div>
                  <div className="rq-id">
                    <div className="rq-name">{it.name}</div>
                    <div className="rq-sub">{it.company}</div>
                  </div>
                </button>
              )
            })}
          </aside>

          {/* draft */}
          <main className="rq-draft">
            <div className="rq-who">
              <div className="avatar">{(current.name || '?').slice(0, 1)}</div>
              <div>
                <div className="rq-who-name">{current.name} <span className="muted">· {current.title || current.company}</span></div>
                <div className="rq-who-sub">
                  {current.source && <span className="src-tag">{current.source}</span>}
                  {current.verdict && <span className={`badge v-${current.verdict}`}>{current.verdict}</span>}
                  {current.edited && <span className="badge s-drafted">edited</span>}
                  {current.decision && <span className={`badge s-${current.decision}`}>{current.decision}</span>}
                </div>
              </div>
            </div>

            {editing ? (
              <div className="edit-form">
                <input className="edit-subject" value={eSubject} onChange={(e) => setESubject(e.target.value)} placeholder="Subject" />
                <textarea className="edit-body" value={eBody} onChange={(e) => setEBody(e.target.value)} rows={14} />
                <div className="edit-actions">
                  <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
                  <button className="btn primary" onClick={saveEdit}>Save changes</button>
                </div>
              </div>
            ) : (
              <div className="drawer-email rq-email">
                <div className="subject">{current.subject}</div>
                <pre className="body">{current.body}</pre>
                {current.signature
                  ? <pre className="body sig">{current.signature}</pre>
                  : <div className="sig-missing">No sender signature set — add a <code>sender</code> block in Settings/config so emails are signed.</div>}
              </div>
            )}

            <div className={`ready ${ready.kind}`}>
              <span className={`dot ${ready.kind === 'ok' ? 'd-ok' : 'd-held'}`} />
              <div className="ready-main">
                <div className="ready-text">{ready.text}</div>
                {current.email && !emailEdit && (
                  <div className="ready-email">
                    {current.email}
                    {current.verify_active && <span className={`badge ${current.verify === 'deliverable' ? 's-approved' : current.verify === 'undeliverable' ? 's-invalid' : 's-held'}`}>{current.verify || 'unchecked'}</span>}
                    <button className="linklike ready-edit" onClick={() => { setEEmail(current.email); setEmailEdit(true) }}>change</button>
                  </div>
                )}
                {(!current.email || emailEdit) && (
                  <div className="ready-form">
                    <input className="field-input" type="email" placeholder="name@company.com" value={eEmail}
                      onChange={(e) => setEEmail(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && saveEmail()} />
                    <button className="btn" onClick={saveEmail}>Save email</button>
                    {emailEdit && <button className="icon-btn" onClick={() => setEmailEdit(false)} aria-label="Cancel"><Icon name="x" size={14} /></button>}
                  </div>
                )}
                {emailErr && <div className="ready-err">{emailErr}</div>}
              </div>
            </div>

            {!editing && (
              <div className="rq-actions">
                <span className="rq-keys">A approve · R reject · E edit · J/K move</span>
                <button className="btn" onClick={startEdit}>Edit</button>
                <button className="btn reject" onClick={() => decide('reject')}><Icon name="x" size={15} /> Reject</button>
                <button className="btn approve" onClick={() => decide('approve')}><Icon name="check" size={15} /> Approve</button>
              </div>
            )}
          </main>

          {/* evidence — the co-star, expanded by default */}
          <aside className="rq-evidence">
            <div className="drawer-label">
              {current.facts.length ? `Grounded in ${current.facts.length} verified ${current.facts.length === 1 ? 'fact' : 'facts'}` : 'Evidence'}
            </div>
            {current.facts.length === 0 ? (
              <p className="muted rq-noev">No sourced facts for this lead. Read the draft carefully before approving.</p>
            ) : (
              <ul className="ev-list">
                <AnimatePresence mode="popLayout">
                  {current.facts.map((f, k) => (
                    <motion.li key={current.key + k} className="ev-card"
                      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * 0.03 }}>
                      <div className="ev-claim">{f.claim}</div>
                      {f.quote && <div className="ev-quote">“{f.quote}”</div>}
                      <div className="ev-meta">
                        <span className="src">{f.source_type || 'source'}</span>
                        {f.published && <span className="ev-date">{f.published}</span>}
                        {f.source_url && <a href={f.source_url} target="_blank" rel="noreferrer" className="ev-link"><Icon name="link" size={12} /> source</a>}
                      </div>
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </aside>
        </div>
      )}
    </div>
  )
}
