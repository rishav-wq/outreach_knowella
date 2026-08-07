import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'

// The attribution spine. Every lead carries the place it came from — a LinkedIn
// group, a community, a publication, an Apollo search — and this page shows what
// each place actually produced. Without it the engage → capture → nurture loop is
// just activity; with it you know where to spend the next hour.

const TYPE_LABEL = {
  linkedin_post: 'LinkedIn', linkedin_group: 'LinkedIn group', community: 'Community',
  publication: 'Publication', event: 'Event', apollo: 'Apollo', import: 'Import',
}

// Reply rate is the only column that compares places of different sizes. A bought
// Apollo list of 4,000 and a LinkedIn thread of 40 are otherwise incomparable —
// the big number always looks better. Null until anything has actually been sent.
const rate = (s) => (s.sent > 0 ? (s.replied / s.sent) * 100 : null)

export default function Sources() {
  const [rows, setRows] = useState(null)
  const [notesFor, setNotesFor] = useState(null)   // source id being annotated
  const [draft, setDraft] = useState('')

  const load = () => api.listSources().then(setRows).catch(() => setRows([]))
  useEffect(() => { load() }, [])

  const saveNotes = async (id) => {
    await api.setSourceNotes(id, draft)
    setNotesFor(null); setDraft(''); load()
  }
  const remove = async (s) => {
    if (!window.confirm(`Delete "${s.name}"? Its leads stay in the Library, they just lose the attribution.`)) return
    await api.deleteSource(s.id); load()
  }

  if (rows === null) return <div><Skeleton h={40} /><Skeleton h={200} r={10} style={{ marginTop: 14 }} /></div>

  const totals = rows.reduce((a, r) => ({
    leads: a.leads + r.leads, sent: a.sent + r.sent,
    replied: a.replied + r.replied, meetings: a.meetings + r.meetings,
  }), { leads: 0, sent: 0, replied: 0, meetings: 0 })

  return (
    <div>
      <div className="lib-head">
        <div>
          <div className="dash-eyebrow">Sources</div>
          <div className="lib-title">
            {rows.length} <small>
              {rows.length === 1 ? 'place' : 'places'}, {totals.leads.toLocaleString()} leads,{' '}
              {totals.replied.toLocaleString()} {totals.replied === 1 ? 'reply' : 'replies'}, {totals.meetings} meetings
            </small>
          </div>
          <p className="dash-sub">
            Where every lead came from and what that place produced. Capture from a LinkedIn thread with the
            extension, name the group it lives in, and its contribution shows up here — so you can spend the
            next hour where it actually pays.
          </p>
        </div>
      </div>

      {rows.length === 0 ? (
        <motion.div className="empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <div className="empty-icon"><Icon name="list" size={24} /></div>
          <h3>No sources yet</h3>
          <p className="muted">Pull from Apollo, import a CSV, or capture a LinkedIn thread — each one registers here automatically.</p>
        </motion.div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Source</th><th>Type</th><th>Leads</th><th>With email</th>
                <th>Sent</th><th>Engaged</th><th>Replied</th>
                <th title="Replies ÷ sent. The number to compare places by.">Reply rate</th>
                <th>Meetings</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <td>
                    <b>{s.name}</b>
                    {s.url && <a href={s.url} target="_blank" rel="noreferrer" className="src-link" title={s.url}> ↗</a>}
                    {notesFor === s.id ? (
                      <div className="ready-form" style={{ marginTop: 8 }}>
                        <input className="field-input" autoFocus value={draft} placeholder="Questions people asked here — your content backlog"
                          onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && saveNotes(s.id)} />
                        <button className="btn" onClick={() => saveNotes(s.id)}>Save</button>
                        <button className="btn" onClick={() => setNotesFor(null)}>Cancel</button>
                      </div>
                    ) : (
                      <div className="src-notes" onClick={() => { setNotesFor(s.id); setDraft(s.notes || '') }}
                        title="What are people asking here? Click to note it — this is the newsletter backlog.">
                        {s.notes || <span className="muted">+ note what they’re asking</span>}
                      </div>
                    )}
                  </td>
                  <td><span className="fn-tag fn-other">{TYPE_LABEL[s.type] || s.type}</span></td>
                  <td><b>{s.leads}</b></td>
                  <td className="muted">{s.with_email}</td>
                  <td className="muted">{s.sent}</td>
                  <td className="muted">{s.engaged}</td>
                  <td>{s.replied > 0 ? <span className="badge s-approved">{s.replied}</span> : <span className="muted">0</span>}</td>
                  <td className={rate(s) !== null && rate(s) >= 2 ? 'src-rate-good' : 'muted'}>
                    {rate(s) === null ? '—' : `${rate(s).toFixed(2)}%`}
                  </td>
                  <td>{s.meetings > 0 ? <span className="badge s-approved">{s.meetings}</span> : <span className="muted">0</span>}</td>
                  <td><button className="icon-btn" title="Delete source" onClick={() => remove(s)}><Icon name="trash" size={13} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
