import { useState } from 'react'
import * as api from '../api'

// One timeline for a lead or a company: notes, what happened in each campaign (sent,
// replied, meeting), stage and owner changes. Newest first, grouped by day; entries
// from before dates were kept sit at the end under "Date unknown".

const KIND = {
  note: 'Note', email_sent: 'Email', reply: 'Reply', meeting: 'Meeting', stage_change: 'Stage',
  owner_change: 'Owner', created: 'Added', enrolled: 'Campaign', edited: 'Edit', person_deleted: 'Deleted',
}
const FILTERS = [
  ['all', 'All'], ['note', 'Notes'], ['email', 'Emails'], ['reply', 'Replies'], ['meeting', 'Meetings'], ['change', 'Changes'],
]
const IN = {
  note: (t) => t === 'note', email: (t) => t === 'email_sent', reply: (t) => t === 'reply', meeting: (t) => t === 'meeting',
  change: (t) => ['stage_change', 'owner_change', 'edited', 'created', 'enrolled', 'person_deleted'].includes(t),
}
export const REPLY_LABEL = {
  interested: 'Interested', not_interested: 'Not interested', opt_out: 'Opted out', ooo: 'Out of office', other: 'Reply',
}

const dayOf = (at) => {
  if (!at) return 'Date unknown'
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? 'Date unknown'
    : d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}
const timeOf = (at) => {
  if (!at || at.length <= 10) return ''
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function NoteComposer({ onSave, placeholder = 'Write a note…' }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const save = async () => {
    if (!text.trim() || busy) return
    setBusy(true); setErr('')
    try { await onSave(text.trim()); setText('') } catch (e) { setErr(api.errorText(e)) }
    setBusy(false)
  }
  return (
    <div className="tl-compose">
      <label className="sr-only" htmlFor="tl-note">Note</label>
      <textarea id="tl-note" className="field-input" rows={2} maxLength={5000} placeholder={placeholder} value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save() }} />
      <div className="tl-compose-row">
        <span className="muted">Ctrl+Enter to save</span>
        {err && <span className="ready-err" style={{ margin: 0 }}>{err}</span>}
        <button className="btn primary" disabled={busy || !text.trim()} onClick={save}>{busy ? 'Saving…' : 'Save note'}</button>
      </div>
    </div>
  )
}

export default function Timeline({ items, me, onChanged, showWho = false }) {
  const [filter, setFilter] = useState('all')
  const [err, setErr] = useState('')
  const counts = Object.fromEntries(FILTERS.map(([k]) => [k, k === 'all' ? items.length : items.filter((x) => IN[k](x.type)).length]))
  const shown = filter === 'all' ? items : items.filter((x) => IN[filter](x.type))
  const pinned = items.filter((x) => x.type === 'note' && x.pinned)
  const groups = []
  for (const x of shown) {
    const day = dayOf(x.at)
    if (!groups.length || groups[groups.length - 1].day !== day) groups.push({ day, items: [] })
    groups[groups.length - 1].items.push(x)
  }
  const act = async (fn) => { setErr(''); try { await fn(); onChanged?.() } catch (e) { setErr(api.errorText(e)) } }
  const canDelete = (x) => me && (me.role === 'admin' || x.by_id === me.id)
  return (
    <div className="tl">
      {pinned.length > 0 && (
        <div className="tl-pinned">
          {pinned.map((x) => <div key={x.id}><b>Pinned note</b> · {x.body}</div>)}
        </div>
      )}
      <div className="tl-filters" role="group" aria-label="Show">
        {FILTERS.map(([k, label]) => (
          <button key={k} className={`chip ${filter === k ? 'on' : ''}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>
            {label} <span className="chip-n">{counts[k]}</span>
          </button>
        ))}
      </div>
      {err && <div className="banner error">{err}</div>}
      {groups.length === 0 && <div className="muted tl-empty">Nothing here yet.</div>}
      {groups.map((g) => (
        <div key={g.day} className="tl-day">
          <div className="tl-day-h">{g.day}</div>
          {g.items.map((x) => (
            <div key={x.id} className={`tl-row tl-${x.type}`}>
              <span className={`tl-kind k-${x.type}`}>{KIND[x.type] || x.type}</span>
              <div className="tl-main">
                <div className="tl-title">
                  {x.type === 'note' ? <span>Note{x.by ? ` by ${x.by}` : ''}</span> : <span>{x.body}</span>}
                  {x.type === 'reply' && x.meta?.label && <span className="tl-chip">{REPLY_LABEL[x.meta.label] || x.meta.label}</span>}
                  {showWho && x.who && <span className="muted">· {x.who}</span>}
                  <span className="tl-meta">{[timeOf(x.at), x.type !== 'note' && x.by ? x.by : ''].filter(Boolean).join(' · ')}</span>
                </div>
                {x.type === 'note' && <div className="tl-body">{x.body}</div>}
                {x.type === 'note' && (
                  <div className="tl-actions">
                    <button className="linklike" onClick={() => act(() => api.pinNote(x.id, !x.pinned))}>{x.pinned ? 'Unpin' : 'Pin'}</button>
                    {canDelete(x) && (
                      <button className="linklike" onClick={() => {
                        if (window.confirm('Delete this note?')) act(() => api.deleteNote(x.id))
                      }}>Delete</button>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
