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

// One follow-up email (sequence step 2 or 3): collapsed preview, inline edit.
function FollowupCard({ campaign, leadKey, fu, onSaved }) {
  const [editing, setEditing] = useState(false)
  const [s, setS] = useState(fu.subject)
  const [b, setB] = useState(fu.body)
  const save = async () => {
    await api.editFollowup(campaign, leadKey, fu.step, s, b)
    onSaved(s, b)
    setEditing(false)
  }
  const label = fu.step === 2 ? 'Follow-up 1 · day 3' : 'Follow-up 2 · day 7'
  return (
    <div className="fu-card">
      <div className="fu-head">
        <span className="fu-tag">{label}</span>
        <span className="fu-subject">{fu.subject}</span>
        {!editing && <button className="linklike" onClick={() => { setS(fu.subject); setB(fu.body); setEditing(true) }}>edit</button>}
      </div>
      {editing ? (
        <div className="edit-form">
          <input className="edit-subject" value={s} onChange={(e) => setS(e.target.value)} />
          <textarea className="edit-body" value={b} onChange={(e) => setB(e.target.value)} rows={6} />
          <div className="edit-actions">
            <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn primary" onClick={save}>Save</button>
          </div>
        </div>
      ) : (
        <pre className="fu-body">{fu.body}</pre>
      )}
    </div>
  )
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
  const [sendBlock, setSendBlock] = useState('')
  const [guard, setGuard] = useState(null)
  const [sending, setSending] = useState(false)
  const [approvingAll, setApprovingAll] = useState(false)  // bulk-approve in flight
  const [sendProgress, setSendProgress] = useState(null)   // {sent, done, total} live during a send
  const [fuOpen, setFuOpen] = useState(false)              // follow-ups collapsed by default
  const [reviseOpen, setReviseOpen] = useState(false)      // AI-revise box collapsed by default
  const [boxes, setBoxes] = useState([])          // all Apollo mailboxes
  const [mailboxIds, setMailboxIds] = useState([])// which ones this campaign sends from (rotates)
  const [mboxOpen, setMboxOpen] = useState(false)
  const [refineText, setRefineText] = useState('')
  const [refining, setRefining] = useState(false)
  const [refineErr, setRefineErr] = useState('')
  const poll = useRef(null)

  const loadStatus = () =>
    api.getStatus(campaign).then((s) => { setSendable(!!s.sendable); setSendBlock(s.send_block || ''); setGuard(s.guardrails || null) }).catch(() => {})
  const load = () => api.getReview(campaign)
    .then((d) => { setItems(d); setI((prev) => Math.min(prev, Math.max(0, d.length - 1))) })
    .catch(() => setItems([]))

  useEffect(() => {
    setItems(null); setI(0); setEditing(false); setBoxes([]); setMailboxIds([]); setMboxOpen(false)
    load(); loadStatus()
    api.getMailboxes(campaign).then((d) => {
      setBoxes(d.mailboxes || [])
      setMailboxIds(d.current_ids || [])
    }).catch(() => {})
    return () => clearInterval(poll.current)
  }, [campaign])

  const emailOf = (id) => (boxes.find((b) => b.id === id) || {}).email || ''
  const sendFrom = mailboxIds.length === 0 ? ''
    : mailboxIds.length === 1 ? emailOf(mailboxIds[0])
    : `${emailOf(mailboxIds[0])} + ${mailboxIds.length - 1} more (rotating)`

  // toggle which mailboxes this campaign rotates through, right where you review
  const toggleMailbox = async (id) => {
    const prev = mailboxIds
    const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    setMailboxIds(next)
    try { await api.setMailbox(campaign, next) } catch { setMailboxIds(prev) }
  }

  const current = items && items[i]
  const total = items?.length || 0
  const decidedCount = items?.filter((it) => it.decision).length || 0
  const approvedCount = items?.filter((it) => it.decision === 'approved').length || 0
  const approvable = items?.filter((it) => !it.decision && it.email).length || 0  // pending + sendable
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

  const [excluding, setExcluding] = useState(false)   // key pending exclude-confirm

  // remove a not-a-fit lead from the campaign entirely (drafts cleared), keeping
  // it in the master library. Distinct from Reject, which keeps it in-campaign.
  const doExclude = async () => {
    const key = current.key
    setExcluding(false)
    setItems((prev) => prev.filter((it) => it.key !== key))   // drop from the queue
    setI((idx) => Math.max(0, Math.min(idx, (items?.length || 1) - 2)))
    try { await api.excludeLead(campaign, key) } catch { load() }
  }

  // permanently delete a lead — gone from this campaign AND the leads library, for
  // junk rows you want cleared, not kept. Distinct from "Not a fit" (which excludes
  // but keeps the lead in the library). Any row can be deleted, not just the current.
  const doDelete = async (key, name) => {
    if (!window.confirm(`Delete ${name || 'this lead'} permanently? It’s removed from this campaign and your leads library and can’t be recovered.`)) return
    const list = items || []
    const delIdx = list.findIndex((it) => it.key === key)
    const next = list.filter((it) => it.key !== key)
    setItems(next)
    setI((cur) => Math.max(0, Math.min(delIdx !== -1 && delIdx < cur ? cur - 1 : cur, next.length - 1)))
    try { await api.bulkDeleteLeads(campaign, [key]) } catch { load() }
  }

  const saveEdit = async () => {
    const key = current.key
    await api.editEmail(campaign, key, eSubject, eBody)
    patch(key, { subject: eSubject, body: eBody, edited: true })
    setEditing(false)
  }
  const startEdit = () => { setESubject(current.subject); setEBody(current.body); setEditing(true) }

  const doRefine = async () => {
    const key = current.key
    const instruction = refineText.trim()
    if (!instruction || refining) return
    setRefining(true); setRefineErr('')
    try {
      const r = await api.refineEmail(campaign, key, instruction)
      // the revise also regenerates the follow-ups (they're written from the first
      // email), so refresh them here too, not just the main draft
      patch(key, { subject: r.subject, body: r.body, edited: true, ...(r.followups ? { followups: r.followups } : {}) })
      setRefineText('')
    } catch (e) {
      setRefineErr(`Couldn’t tweak: ${e.message || e}`)
    } finally {
      setRefining(false)
    }
  }

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

  useEffect(() => { setEditing(false); setEmailEdit(false); setEmailErr(''); setRefineText(''); setRefineErr(''); setExcluding(false); setFuOpen(false); setReviseOpen(false) }, [i])

  const sendApproved = async () => {
    if (!window.confirm(`Send ${approvedCount} approved ${approvedCount === 1 ? 'email' : 'emails'} through Apollo? This is the real send.`)) return
    setSending(true); setSendProgress({ sent: 0, done: 0, total: approvedCount })
    let r
    try {
      r = await api.runPipeline(campaign, true)
    } catch (e) {   // a failed request must never fail SILENTLY (401, network, 500…)
      setSending(false); setSendProgress(null)
      window.alert(`Send failed to start: ${e.message || e}. If this mentions a session or 401, refresh the page and try again.`)
      return
    }
    if (!r.started) {
      setSending(false); setSendProgress(null)
      window.alert(`Send didn't start: ${r.reason || 'unknown reason'}. If a run is already going, wait for it to finish (watch the Overview) and try again.`)
      return
    }
    poll.current = setInterval(async () => {
      const s = await api.getRunStatus(campaign)
      if (s.progress) setSendProgress(s.progress)
      if (!s.running) { clearInterval(poll.current); setSending(false); setSendProgress(null); load(); loadStatus() }
    }, 1500)
  }

  // bulk-approve every pending, sendable draft — the fast path for verbatim campaigns
  // where all drafts are the same template. Rejections are respected server-side.
  const approveAll = async () => {
    if (!approvable || approvingAll) return
    if (!window.confirm(`Approve all ${approvable} pending ${approvable === 1 ? 'draft' : 'drafts'}? Leads you've rejected stay rejected — you can still review or change any before sending.`)) return
    setApprovingAll(true)
    try { await api.approveAll(campaign); await load() }
    catch { /* leave the queue untouched if it fails */ }
    finally { setApprovingAll(false) }
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

  const sentShown = Math.min(sendProgress?.sent || 0, approvedCount)   // never display more than were approved
  const sendPct = approvedCount ? Math.round((sentShown / approvedCount) * 100) : 0
  const header = (
    <>
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
        {boxes.length > 0 && (
          <div className="mbox-select">
            <button className="src-select mbox-btn" onClick={() => setMboxOpen((o) => !o)}
              title="Which Apollo mailboxes this campaign sends from — sends rotate across them">
              {mailboxIds.length === 0 ? 'choose mailboxes…'
                : mailboxIds.length === 1 ? emailOf(mailboxIds[0])
                : `${mailboxIds.length} mailboxes`}
              <Icon name="chevron" size={13} />
            </button>
            {mboxOpen && (
              <>
                <div className="drawer-backdrop" style={{ background: 'transparent', zIndex: 39 }} onClick={() => setMboxOpen(false)} />
                <div className="mbox-menu">
                  {boxes.map((b) => (
                    <label key={b.id} className="mbox-opt">
                      <input type="checkbox" checked={mailboxIds.includes(b.id)} disabled={!b.active} onChange={() => toggleMailbox(b.id)} />
                      {b.email}{b.active ? '' : ' (inactive)'}
                    </label>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
        {guardLabel() && <span className="guard-note">{guardLabel()}</span>}
        {!sendable && sendBlock && <span className="send-block" title={sendBlock}>{sendBlock}</span>}
        {approvable > 0 && (
          <button className="btn" disabled={approvingAll} onClick={approveAll}
            title="Approve every pending draft at once — leads you've rejected are left as-is">
            {approvingAll ? <><span className="spinner" /> Approving…</> : `Approve all ${approvable}`}
          </button>
        )}
        <button className="btn primary" disabled={!sendable || !approvedCount || sending}
          title={!sendable ? sendBlock : ''} onClick={sendApproved}>
          {sending
            ? <><span className="spinner" /> Sending {sendProgress ? `${sentShown}/${approvedCount}` : '…'}</>
            : `Send ${approvedCount} approved`}
        </button>
      </div>
    </div>
    {sending && (
      <div className="send-progress" title={`${sendProgress?.sent || 0} of ${approvedCount} sent`}>
        <i style={{ width: `${sendPct}%` }} />
        <span className="send-progress-label">Sending {sentShown}/{approvedCount}…</span>
      </div>
    )}
    </>
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
  // Evidence panel presence is a property of the CAMPAIGN, not the lead: show it only
  // when the campaign actually produces facts (any queued lead has some), so it never
  // flickers row-to-row. A factless lead in a research campaign still shows the panel.
  const showEvidence = items.some((it) => (it.facts || []).length > 0)

  return (
    <div className="review">
      {header}
      {view === 'board' ? (
        <Kanban campaign={campaign} embedded />
      ) : (
        <div className={`review-work ${showEvidence ? '' : 'no-evidence'}`}>
          {/* queue rail */}
          <aside className="rq-list">
            {items.map((it, idx) => {
              const r = readiness(it)
              return (
                <div key={it.key} className="rq-item-wrap">
                  <button className={`rq-item ${idx === i ? 'on' : ''} ${it.decision || ''}`} onClick={() => setI(idx)}>
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
                  <button className="rq-del" aria-label={`Delete ${it.name}`}
                    title="Delete this lead — removes it from the campaign and your leads library"
                    onClick={() => doDelete(it.key, it.name)}>
                    <Icon name="trash" size={13} />
                  </button>
                </div>
              )
            })}
          </aside>

          {/* draft — an email document you sign off, headed like a form */}
          <main className="rq-draft">
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
              <>
                <div className="doc">
                  <div className="doc-head">
                    <div className="doc-row">
                      <span className="doc-k">To</span>
                      <span className="doc-v">
                        <b>{current.name}</b>{(current.title || current.company) && <span className="muted"> · {current.title || current.company}</span>}
                        {current.email && !emailEdit && (
                          <span className="doc-email">
                            {current.email}
                            {current.verify_active && <span className={`badge ${current.verify === 'deliverable' ? 's-approved' : current.verify === 'undeliverable' ? 's-invalid' : 's-held'}`}>{current.verify || 'unchecked'}</span>}
                            <button className="linklike" onClick={() => { setEEmail(current.email); setEmailEdit(true) }}>change</button>
                          </span>
                        )}
                        {(!current.email || emailEdit) && (
                          <span className="ready-form">
                            <input className="field-input" type="email" placeholder="name@company.com" value={eEmail}
                              onChange={(e) => setEEmail(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && saveEmail()} />
                            <button className="btn" onClick={saveEmail}>Save email</button>
                            {emailEdit && <button className="icon-btn" onClick={() => setEmailEdit(false)} aria-label="Cancel"><Icon name="x" size={14} /></button>}
                          </span>
                        )}
                      </span>
                    </div>
                    <div className="doc-row"><span className="doc-k">From</span><span className="doc-v">{sendFrom || <span className="muted">choose a mailbox in campaign settings</span>}</span></div>
                    <div className="doc-row"><span className="doc-k">Subject</span><span className="doc-v doc-subject">{current.subject}</span></div>
                    <div className="doc-tags">
                      <span className={`badge ${ready.kind === 'ok' ? 's-approved' : 's-held'}`}>{ready.text}</span>
                      {current.decision && <span className={`badge s-${current.decision}`}>{current.decision}</span>}
                      <span className="doc-meta" title="how this draft was produced">
                        {[current.source,
                          current.verbatim ? 'verbatim' : (current.variant === 'plain' ? 'control' : 'fact-led'),
                          !current.verbatim && current.verdict,
                          current.edited && 'edited'].filter(Boolean).join(' · ')}
                      </span>
                    </div>
                  </div>
                  <pre className="body">{current.body}</pre>
                  {current.signature
                    ? <pre className="body sig">{current.signature}</pre>
                    : <div className="sig-missing">No sender signature set — add a <code>sender</code> block in the campaign config so emails are signed.</div>}
                </div>
                {emailErr && <div className="ready-err">{emailErr}</div>}
                {(current.followups || []).length > 0 && (
                  <div className="fu-block">
                    <button type="button" className="fu-toggle" onClick={() => setFuOpen((o) => !o)} aria-expanded={fuOpen}>
                      <Icon name="chevron" size={13} className={`chev ${fuOpen ? 'up' : ''}`} />
                      {current.followups.length} follow-up{current.followups.length === 1 ? '' : 's'}
                      <span className="muted"> — auto-send to non-repliers; anyone who replies exits</span>
                    </button>
                    {fuOpen && current.followups.map((fu) => (
                      <FollowupCard key={fu.step} campaign={campaign} leadKey={current.key} fu={fu}
                        onSaved={(subject, body) => patch(current.key, {
                          followups: current.followups.map((x) => x.step === fu.step ? { ...x, subject, body } : x),
                        })} />
                    ))}
                  </div>
                )}
              </>
            )}

            {!editing && (
              <div className="rq-footer">
                {excluding && (
                  <div className="exclude-confirm">
                    <div className="exclude-confirm-text">
                      Remove <b>{current.name}</b> from <b>{campaign}</b>? Its draft and follow-ups are deleted and it won’t be emailed in this campaign — but the lead stays in your leads library for future use.
                    </div>
                    <div className="exclude-confirm-actions">
                      <button className="btn" onClick={() => setExcluding(false)}>Keep in campaign</button>
                      <button className="btn reject" onClick={doExclude}><Icon name="x" size={14} /> Remove lead</button>
                    </div>
                  </div>
                )}
                {!reviseOpen ? (
                  <button type="button" className="ai-tweak-toggle" onClick={() => setReviseOpen(true)}>
                    <Icon name="refresh" size={13} /> Revise with AI
                  </button>
                ) : (
                  <div className="ai-tweak">
                    <span className="ai-tweak-k"><Icon name="refresh" size={13} /> Revise</span>
                    <input className="ai-tweak-input" value={refineText} disabled={refining} autoFocus
                      placeholder="ask AI for a change — “make it shorter”, “lead with their hiring”, “warmer tone” (updates the follow-ups too)"
                      onChange={(e) => setRefineText(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') doRefine() }} />
                    <button className="btn ella" onClick={doRefine} disabled={refining || !refineText.trim()}>
                      {refining ? <><span className="spinner" /> revising…</> : 'Revise'}
                    </button>
                    <button className="icon-btn" onClick={() => setReviseOpen(false)} aria-label="Close revise"><Icon name="x" size={14} /></button>
                  </div>
                )}
                {refineErr && <div className="ready-err">{refineErr}</div>}
                <div className="rq-actions">
                  <span className="rq-keys">A approve · R reject · E edit · J/K move</span>
                  <button className="btn exclude-btn" onClick={() => setExcluding(true)}
                    title="Not a fit — remove from this campaign (kept in the leads library)">Not a fit</button>
                  <button className="btn" onClick={startEdit}>Edit</button>
                  <button className="btn reject" onClick={() => decide('reject')}><Icon name="x" size={15} /> Reject</button>
                  <button className="btn approve stamp" onClick={() => decide('approve')}><Icon name="check" size={15} /> Approve</button>
                </div>
              </div>
            )}
          </main>

          {/* evidence — shown only when the campaign produces facts (consistent per campaign) */}
          {showEvidence && (
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
          )}
        </div>
      )}
    </div>
  )
}
