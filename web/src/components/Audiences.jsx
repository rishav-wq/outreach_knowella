import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'

// Saved audiences: named Library filters, resolved LIVE at every use — an
// audience's count grows as the Library grows, no stale lists to maintain.
const EMPTY = { topics: [], statuses: [], exclude_sent: true, engagement: '' }

export default function Audiences() {
  const [items, setItems] = useState(null)
  const [topics, setTopics] = useState([])
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [flt, setFlt] = useState(EMPTY)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = () => api.listAudiences().then(setItems).catch(() => setItems([]))
  useEffect(() => {
    load()
    api.getMarketingMeta().then((d) => setTopics(d.topics || [])).catch(() => {})
  }, [])

  useEffect(() => {
    if (!creating) return
    const t = setTimeout(() => api.previewAudience(flt).then(setPreview).catch(() => setPreview(null)), 350)
    return () => clearTimeout(t)
  }, [creating, flt])

  const toggleTopic = (t) => setFlt((f) => ({ ...f,
    topics: f.topics.includes(t) ? f.topics.filter((x) => x !== t) : [...f.topics, t] }))

  const save = async () => {
    setBusy(true)
    try {
      await api.createAudience(name.trim(), flt)
      setCreating(false); setName(''); setFlt(EMPTY); setPreview(null)
      load()
    } finally { setBusy(false) }
  }

  const remove = async (a) => {
    if (!window.confirm(`Delete audience "${a.name}"? Blasts that used it keep their own copy of the filter.`)) return
    await api.deleteAudience(a.id); load()
  }

  if (items === null) return <div><Skeleton h={80} r={10} /><Skeleton h={80} r={10} style={{ marginTop: 12 }} /></div>

  return (
    <div className="mkt">
      <div className="mkt-head">
        <div>
          <div className="section-label" style={{ marginBottom: 4 }}>Marketing · audiences</div>
          <div className="muted" style={{ fontSize: 12.5 }}>Named Library segments, resolved live at every send — counts grow as the Library grows.</div>
        </div>
        {!creating && <button className="btn primary" onClick={() => setCreating(true)}><Icon name="plus" size={14} /> New audience</button>}
      </div>

      {creating && (
        <motion.div className="mkt-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <input className="field-input" placeholder="Audience name — e.g. Trucking, never pitched" value={name}
            onChange={(e) => setName(e.target.value)} autoFocus />
          <div className="muted" style={{ fontSize: 11.5, margin: '12px 0 6px' }}>Topics (any match; none = whole Library)</div>
          <div className="chip-row">
            {topics.map((t) => (
              <button key={t} className={`chip ${flt.topics.includes(t) ? 'on' : ''}`} onClick={() => toggleTopic(t)}>{t}</button>
            ))}
          </div>
          <div className="mkt-aud-opts">
            <label className="use-ai-toggle">
              <input type="checkbox" checked={!!flt.exclude_sent}
                onChange={(e) => setFlt({ ...flt, exclude_sent: e.target.checked })} />
              <span><b>Skip anyone sales already emailed</b></span>
            </label>
            <select className="src-select" value={flt.engagement}
              onChange={(e) => setFlt({ ...flt, engagement: e.target.value })}
              title="Narrow to people who engaged with a previous blast — the warm slice">
              <option value="">Any engagement</option>
              <option value="opened">Opened a blast</option>
              <option value="clicked">Clicked a blast</option>
            </select>
          </div>
          <div className="mkt-actions">
            <div className="mkt-count" style={{ margin: 0 }}><b>{preview ? preview.count : '…'}</b> people right now</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn" onClick={() => { setCreating(false); setFlt(EMPTY); setName('') }}>Cancel</button>
              <button className="btn primary" disabled={!name.trim() || busy} onClick={save}>
                {busy ? <><span className="spinner" /> Saving…</> : 'Save audience'}
              </button>
            </div>
          </div>
        </motion.div>
      )}

      {items.length === 0 && !creating && (
        <div className="empty" style={{ marginTop: 30 }}>
          <div className="empty-icon"><Icon name="users" size={24} /></div>
          <h3>No audiences yet</h3>
          <p className="muted">Save your first segment — e.g. “Trucking, never pitched” or “Clicked a blast” — and reuse it across blasts and newsletters.</p>
          <div className="empty-actions"><button className="btn primary" onClick={() => setCreating(true)}>New audience</button></div>
        </div>
      )}

      {items.map((a) => (
        <div className="mkt-card" key={a.id}>
          <div className="mkt-card-top">
            <div>
              <b>{a.name}</b>
              <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
                {(a.filter.topics || []).length ? `topics: ${a.filter.topics.join(', ')}` : 'whole Library'}
                {a.filter.exclude_sent ? ' · never sales-emailed' : ''}
                {a.filter.engagement ? ` · ${a.filter.engagement} a blast` : ''}
              </div>
            </div>
            <div className="mkt-card-actions">
              <span className="mkt-aud-count"><b>{a.count}</b> people</span>
              <button className="icon-btn" title="Delete" onClick={() => remove(a)}><Icon name="trash" size={14} /></button>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
