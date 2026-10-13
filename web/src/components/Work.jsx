import { useState } from 'react'
import * as api from '../api'

// A BDR's daily work, shared by the lead panel and the Today page: logging a call (with
// the playbook's outcome codes), a LinkedIn touch or an email sent elsewhere; tasks with
// due dates. The server counts what's logged toward today's targets (src/work.py).

export const OUTCOMES = [
  ['no_answer', 'No answer'], ['voicemail', 'Voicemail'], ['gatekeeper', 'Gatekeeper'],
  ['conversation', 'Conversation'], ['meeting', 'Meeting booked'], ['not_a_fit', 'Not a fit'],
]
export const LI_ACTIONS = [
  ['view', 'Viewed profile'], ['follow', 'Followed'], ['comment', 'Commented'],
  ['connect', 'Connection request'], ['message', 'Message or voice note'],
]
export const TASK_KINDS = [['call', 'Call'], ['email', 'Email'], ['linkedin', 'LinkedIn'], ['todo', 'To-do']]
export const OUTCOME_LABEL = Object.fromEntries(OUTCOMES)
export const LI_LABEL = Object.fromEntries(LI_ACTIONS)
const KIND_LABEL = Object.fromEntries(TASK_KINDS)
const RETRY = new Set(['no_answer', 'voicemail', 'gatekeeper'])   // outcomes that usually mean "try again"

const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d) }
export const addDays = (s, n) => { const d = parse(s); d.setDate(d.getDate() + n); return api.localDay(d) }
export const addBusinessDays = (n, from = api.localDay()) => {
  const d = parse(from)
  while (n > 0) { d.setDate(d.getDate() + 1); if (d.getDay() !== 0 && d.getDay() !== 6) n -= 1 }
  return api.localDay(d)
}
export const fmtDay = (s) => (s ? parse(s).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) : '')

// --- log a call, LinkedIn touch or email ---------------------------------------------------
export function LogTouch({ personId, personName = '', initialKind = 'call', task = null, onSaved, onCancel }) {
  const [kind, setKind] = useState(task && task.kind !== 'todo' ? task.kind : initialKind)
  const [outcome, setOutcome] = useState('')
  const [action, setAction] = useState('')
  const [note, setNote] = useState('')
  const [reason, setReason] = useState('')
  const [follow, setFollow] = useState(false)
  const [fu, setFu] = useState({ kind: 'call', due: addBusinessDays(2), title: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const ready = kind === 'call' ? !!outcome : kind === 'linkedin' ? !!action : true
  const pickOutcome = (o) => {
    setOutcome(o)
    setFollow(RETRY.has(o))           // a no-answer usually means another try; a meeting doesn't
    if (RETRY.has(o)) setFu((f) => ({ ...f, kind: 'call' }))
  }
  const save = async () => {
    if (!ready || busy) return
    setBusy(true); setErr('')
    try {
      await api.logTouch(personId, {
        kind, outcome: kind === 'call' ? outcome : '', action: kind === 'linkedin' ? action : '', note,
        not_fit_reason: outcome === 'not_a_fit' ? reason : '', task_id: task?.id || '',
        ...(follow ? { follow_up_due: fu.due, follow_up_kind: fu.kind, follow_up_title: fu.title } : {}),
      })
      onSaved?.()
    } catch (e) { setErr(api.errorText(e)); setBusy(false) }
  }
  const doneWithoutLog = async () => {
    setBusy(true); setErr('')
    try { await api.updateTask(task.id, { status: 'done' }); onSaved?.() } catch (e) { setErr(api.errorText(e)); setBusy(false) }
  }
  return (
    <div className="log-form" role="group" aria-label="Log">
      <div className="log-head">
        <div className="seg" role="tablist" aria-label="What happened">
          {[['call', 'Call'], ['linkedin', 'LinkedIn'], ['email', 'Email']].map(([k, l]) => (
            <button key={k} role="tab" aria-selected={kind === k} className={kind === k ? 'on' : ''} onClick={() => setKind(k)}>{l}</button>
          ))}
        </div>
        <span className="muted">{task ? `Task: ${task.title}` : personName}</span>
      </div>
      {kind === 'call' && (
        <div className="chip-row" role="group" aria-label="Outcome">
          {OUTCOMES.map(([k, l]) => (
            <button key={k} type="button" className={`chip ${outcome === k ? 'on' : ''}`} aria-pressed={outcome === k} onClick={() => pickOutcome(k)}>{l}</button>
          ))}
        </div>
      )}
      {kind === 'linkedin' && (
        <div className="chip-row" role="group" aria-label="What you did">
          {LI_ACTIONS.map(([k, l]) => (
            <button key={k} type="button" className={`chip ${action === k ? 'on' : ''}`} aria-pressed={action === k} onClick={() => setAction(k)}>{l}</button>
          ))}
        </div>
      )}
      {kind === 'email' && <div className="muted log-hint">An email you sent outside the app (Outlook, Gmail). Emails sent by a campaign are counted on their own.</div>}
      {outcome === 'not_a_fit' && kind === 'call' && (
        <input className="field-input" maxLength={300} placeholder="Why not a fit? (it shapes who we target)" aria-label="Why not a fit"
          value={reason} onChange={(e) => setReason(e.target.value)} />
      )}
      <textarea className="field-input" rows={2} maxLength={5000} aria-label="Notes" placeholder="Notes (optional)"
        value={note} onChange={(e) => setNote(e.target.value)} />
      <label className="field-check log-follow">
        <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Add a follow-up
      </label>
      {follow && (
        <div className="log-fu fu-follow">
          <select className="field-input" aria-label="Follow-up kind" value={fu.kind} onChange={(e) => setFu({ ...fu, kind: e.target.value })}>
            {TASK_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <input className="field-input" type="date" aria-label="Follow-up date" value={fu.due} onChange={(e) => setFu({ ...fu, due: e.target.value })} />
          <input className="field-input" maxLength={300} aria-label="Follow-up title" placeholder="Title (optional)"
            value={fu.title} onChange={(e) => setFu({ ...fu, title: e.target.value })} />
        </div>
      )}
      {err && <div className="banner error" style={{ margin: 0 }}>{err}</div>}
      <div className="log-actions">
        {task && <button className="linklike" disabled={busy} onClick={doneWithoutLog}>Mark done without logging</button>}
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="btn primary" onClick={save} disabled={!ready || busy || (follow && !fu.due)}>
          {busy ? 'Saving…' : task ? 'Log and complete' : 'Log it'}
        </button>
      </div>
    </div>
  )
}

// --- add a task -----------------------------------------------------------------------------
export function TaskForm({ personId = '', onSaved, onCancel }) {
  const [f, setF] = useState({ title: '', kind: personId ? 'call' : 'todo', due: api.localDay() })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const save = async () => {
    if (!f.title.trim() || busy) return
    setBusy(true); setErr('')
    try { await api.createTask({ ...f, person_id: personId }); onSaved?.() } catch (e) { setErr(api.errorText(e)); setBusy(false) }
  }
  return (
    <div className="log-form" role="group" aria-label="New task">
      <div className="log-fu fu-task">
        <input className="field-input" autoFocus maxLength={300} aria-label="Task" placeholder="What needs doing?"
          value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && save()} />
        <select className="field-input" aria-label="Kind" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          {TASK_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <input className="field-input" type="date" aria-label="Due" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} />
      </div>
      {err && <div className="banner error" style={{ margin: 0 }}>{err}</div>}
      <div className="log-actions">
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="btn primary" onClick={save} disabled={busy || !f.title.trim() || !f.due}>{busy ? 'Saving…' : 'Add task'}</button>
      </div>
    </div>
  )
}

// --- one task ---------------------------------------------------------------------------------
// `onLog(task)`: the host shows the log form for a call, LinkedIn or email task (the lead
// panel does it in its main column); without it, the row opens the form under itself.
export function TaskRow({ t, today = api.localDay(), onOpenPerson, onChanged, onLog, showPerson = true, showOwner = false }) {
  const [logging, setLogging] = useState(false)
  const [err, setErr] = useState('')
  const loggable = t.person_id && t.kind !== 'todo'
  const act = async (patch) => {
    setErr('')
    try { await api.updateTask(t.id, patch); onChanged?.() } catch (e) { setErr(api.errorText(e)) }
  }
  const done = () => {
    if (!loggable) return act({ status: 'done' })
    if (onLog) return onLog(t)
    setLogging(true)
  }
  const overdue = t.due < today
  const due = overdue ? `Overdue · ${fmtDay(t.due)}` : t.due === today ? 'Today' : fmtDay(t.due)
  return (
    <div className={`task-row ${overdue ? 'overdue' : ''}`}>
      <div className="task-line">
        <span className={`task-kind tk-${t.kind}`}>{KIND_LABEL[t.kind] || t.kind}</span>
        <div className="task-main">
          <div className="task-title">{t.title}</div>
          <div className="muted task-sub">
            {showPerson && t.person_id && (
              <button className="linklike inline" onClick={() => onOpenPerson?.(t.person_id)}>
                {t.person_name || 'Lead'}{t.company ? ` · ${t.company}` : ''}
              </button>
            )}
            {showOwner && t.owner_name && <span>{t.owner_name}</span>}
          </div>
        </div>
        <span className={`due-chip ${overdue ? 'late' : t.due === today ? 'now' : ''}`}>{due}</span>
        <div className="task-acts">
          <button className="btn small primary" onClick={done}>{loggable ? `Log ${KIND_LABEL[t.kind].toLowerCase()}` : 'Done'}</button>
          <button className="btn small" title="Move to tomorrow" onClick={() => act({ due: addDays(t.due < today ? today : t.due, 1) })}>Tomorrow</button>
          <button className="btn small ghost" title="Skip this task" onClick={() => act({ status: 'skipped' })}>Skip</button>
        </div>
      </div>
      {err && <div className="banner error" style={{ margin: '6px 0 0' }}>{err}</div>}
      {logging && (
        <LogTouch personId={t.person_id} task={t} onCancel={() => setLogging(false)}
          onSaved={() => { setLogging(false); onChanged?.() }} />
      )}
    </div>
  )
}
