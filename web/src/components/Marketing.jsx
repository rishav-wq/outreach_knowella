import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'

// The marketing engine's cockpit: 1:many blasts (announcements, newsletters) to
// live Library segments via Postmark — one message, one human approval, real
// per-person stats from webhooks. The counterpart to Review's one-lead-at-a-time.

const STATUS_BADGE = { draft: 's-drafted', sending: 's-queued', sent: 's-approved', paused: 's-invalid' }

const EMPTY = { name: '', subject: '', body: '', audience: { topics: [], statuses: [], exclude_sent: true, engagement: '' } }

export default function Marketing() {
  const [blasts, setBlasts] = useState(null)
  const [view, setView] = useState('list')          // 'list' | 'edit'
  const [draft, setDraft] = useState(EMPTY)
  const [draftId, setDraftId] = useState(null)      // editing an existing draft
  const [topics, setTopics] = useState([])
  const [audiences, setAudiences] = useState([])
  const [preview, setPreview] = useState(null)      // {count, sample}
  const [testTo, setTestTo] = useState('')
  const [busy, setBusy] = useState('')              // '', 'test', 'send', 'save'
  const [msg, setMsg] = useState(null)              // {ok, text}
  const poll = useRef(null)
  const debounce = useRef(null)

  const load = () => api.listBlasts().then(setBlasts).catch(() => setBlasts([]))
  useEffect(() => {
    load()
    api.getMarketingMeta().then((d) => setTopics(d.topics || [])).catch(() => {})
    api.listAudiences().then(setAudiences).catch(() => {})
    return () => { clearInterval(poll.current); clearTimeout(debounce.current) }
  }, [])

  // live progress while anything is sending
  useEffect(() => {
    clearInterval(poll.current)
    if (blasts?.some((b) => b.status === 'sending')) {
      poll.current = setInterval(load, 2000)
    }
    return () => clearInterval(poll.current)
  }, [blasts?.some((b) => b.status === 'sending')])  // eslint-disable-line react-hooks/exhaustive-deps

  // audience preview follows the filter as it's edited
  useEffect(() => {
    if (view !== 'edit') return
    clearTimeout(debounce.current)
    debounce.current = setTimeout(() => {
      api.previewAudience(draft.audience).then(setPreview).catch(() => setPreview(null))
    }, 350)
  }, [view, draft.audience])  // eslint-disable-line react-hooks/exhaustive-deps

  const startNew = () => { setDraft(EMPTY); setDraftId(null); setMsg(null); setTestTo(''); setView('edit') }
  const startEdit = (b) => {
    setDraft({ name: b.name, subject: b.subject, body: b.body,
               audience: { topics: [], statuses: [], exclude_sent: true, ...b.audience } })
    setDraftId(b.id); setMsg(null); setView('edit')
  }
  const toggleTopic = (t) => setDraft((d) => ({ ...d, audience: { ...d.audience,
    topics: d.audience.topics.includes(t) ? d.audience.topics.filter((x) => x !== t) : [...d.audience.topics, t] } }))

  const complete = draft.name.trim() && draft.subject.trim() && draft.body.trim()

  // save (create or update) and return the id — test/send both go through here so
  // what you test is always exactly what's stored
  const save = async () => {
    if (draftId) { await api.updateBlast(draftId, draft); return draftId }
    const r = await api.createBlast(draft)
    setDraftId(r.id)
    return r.id
  }

  const doTest = async () => {
    setBusy('test'); setMsg(null)
    try {
      const id = await save()
      const r = await api.testBlast(id, testTo.trim())
      setMsg({ ok: true, text: `Test sent to ${testTo.trim()} (rendered for ${r.rendered_for}). This blast would reach ${r.audience_count} people.` })
      load()
    } catch (e) { setMsg({ ok: false, text: `Test failed: ${String(e.message).slice(0, 220)}` }) }
    finally { setBusy('') }
  }

  const doSend = async () => {
    const n = preview?.count ?? '?'
    if (!window.confirm(`Send this blast to ${n} people via Postmark? This is the real bulk send — every message carries a one-click unsubscribe.`)) return
    setBusy('send'); setMsg(null)
    try {
      const id = await save()
      const r = await api.sendBlast(id)
      if (!r.started) { setMsg({ ok: false, text: `Didn't start: ${r.reason || 'unknown'}` }); return }
      setView('list'); load()
    } catch (e) { setMsg({ ok: false, text: `Send failed: ${String(e.message).slice(0, 220)}` }) }
    finally { setBusy('') }
  }

  const doDelete = async (b) => {
    if (!window.confirm(`Delete "${b.name}"? ${b.status === 'sent' ? 'Its stats go with it.' : ''}`)) return
    await api.deleteBlast(b.id); load()
  }

  if (blasts === null) {
    return <div><Skeleton h={90} r={10} /><Skeleton h={90} r={10} style={{ marginTop: 14 }} /></div>
  }

  // ---------- composer ----------
  if (view === 'edit') {
    return (
      <div className="mkt">
        <button className="ghostlink" onClick={() => setView('list')}>← All blasts</button>
        <div className="mkt-grid">
          <div className="mkt-main">
            <div className="section-label">Compose</div>
            <input className="field-input" placeholder="Internal name — e.g. Ops Brief #1" value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <input className="field-input" placeholder="Subject — merge fields work: {first_name}, {company}" value={draft.subject}
              onChange={(e) => setDraft({ ...draft, subject: e.target.value })} style={{ marginTop: 10 }} />
            <textarea className="field-input mkt-body" rows={14} value={draft.body}
              placeholder={'Hi {first_name},\n\nWrite the issue…\n\n(unsubscribe footer is added automatically to every message)'}
              onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
            <div className="muted" style={{ fontSize: 11.5, marginTop: 6 }}>
              Merge fields: <code>{'{first_name}'}</code> <code>{'{company}'}</code> <code>{'{title}'}</code> — filled per person, same engine as verbatim sales mail.
            </div>

            <div className="mkt-actions">
              <div className="ready-form" style={{ margin: 0 }}>
                <input className="field-input" placeholder="you@knowella.com" value={testTo}
                  onChange={(e) => setTestTo(e.target.value)} style={{ width: 220 }} />
                <button className="btn" disabled={!complete || !testTo.includes('@') || busy !== ''} onClick={doTest}>
                  {busy === 'test' ? <><span className="spinner spinner-dark" /> Sending…</> : 'Send test to me'}
                </button>
              </div>
              <button className="btn approve" disabled={!complete || busy !== '' || !preview?.count} onClick={doSend}
                title={!preview?.count ? 'The audience is empty' : ''}>
                {busy === 'send' ? <><span className="spinner" /> Starting…</> : `Send to ${preview?.count ?? '…'} people`}
              </button>
            </div>
            {msg && <div className={`banner ${msg.ok ? '' : 'error'}`} style={{ marginTop: 12 }}>{msg.text}</div>}
          </div>

          <aside className="mkt-side">
            <div className="section-label">Audience — live from the Library</div>
            {audiences.length > 0 && (
              <select className="src-select" style={{ width: '100%', marginBottom: 12 }} value=""
                title="Load a saved audience's filter into this blast"
                onChange={(e) => {
                  const a = audiences.find((x) => x.id === e.target.value)
                  if (a) setDraft((d) => ({ ...d, audience: { topics: [], statuses: [], exclude_sent: true, engagement: '', ...a.filter } }))
                }}>
                <option value="">Load a saved audience…</option>
                {audiences.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.count})</option>)}
              </select>
            )}
            <label className="use-ai-toggle" style={{ marginBottom: 12 }}>
              <input type="checkbox" checked={!!draft.audience.exclude_sent}
                onChange={(e) => setDraft({ ...draft, audience: { ...draft.audience, exclude_sent: e.target.checked } })} />
              <span><b>Skip anyone sales already emailed</b>
                <span className="muted"> — keeps cold-sequence targets out of bulk mail</span></span>
            </label>
            <div className="muted" style={{ fontSize: 11.5, marginBottom: 6 }}>Topics (any match; none selected = whole Library)</div>
            <div className="chip-row">
              {topics.map((t) => (
                <button key={t} className={`chip ${draft.audience.topics.includes(t) ? 'on' : ''}`} onClick={() => toggleTopic(t)}>{t}</button>
              ))}
              {topics.length === 0 && <span className="muted" style={{ fontSize: 12 }}>No topics tagged yet.</span>}
            </div>
            <select className="src-select" style={{ width: '100%', marginTop: 12 }} value={draft.audience.engagement || ''}
              onChange={(e) => setDraft({ ...draft, audience: { ...draft.audience, engagement: e.target.value } })}
              title="Narrow to people who engaged with a previous blast">
              <option value="">Any engagement</option>
              <option value="opened">Opened a previous blast</option>
              <option value="clicked">Clicked a previous blast</option>
            </select>
            <div className="mkt-count">
              <b>{preview ? preview.count : '…'}</b> recipients
              <div className="muted" style={{ fontSize: 11 }}>emailless + unsubscribed already excluded · deduped across campaigns</div>
            </div>
            {preview?.sample?.length > 0 && (
              <div className="list" style={{ marginTop: 8 }}>
                {preview.sample.map((p) => (
                  <div key={p.email}>{p.name || p.email}<span> — {p.company}</span></div>
                ))}
              </div>
            )}
          </aside>
        </div>
      </div>
    )
  }

  // ---------- list ----------
  return (
    <div className="mkt">
      <div className="mkt-head">
        <div>
          <div className="section-label" style={{ marginBottom: 4 }}>Marketing · blasts &amp; newsletters</div>
          <div className="muted" style={{ fontSize: 12.5 }}>One message to a live Library segment via Postmark — separate pipes from sales, same suppression list.</div>
        </div>
        <button className="btn primary" onClick={startNew}><Icon name="plus" size={14} /> New blast</button>
      </div>

      {blasts.length === 0 && (
        <motion.div className="empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <div className="empty-icon"><Icon name="upload" size={24} /></div>
          <h3>No blasts yet</h3>
          <p className="muted">Compose your first announcement or newsletter issue, test it on yourself, then send it to a Library segment.</p>
          <div className="empty-actions"><button className="btn primary" onClick={startNew}>New blast</button></div>
        </motion.div>
      )}

      {blasts.map((b) => {
        const s = b.stats || {}
        const pct = b.progress?.total ? Math.round((b.progress.done / b.progress.total) * 100) : 0
        return (
          <div className="mkt-card" key={b.id}>
            <div className="mkt-card-top">
              <div>
                <b>{b.name}</b>
                <span className={`badge ${STATUS_BADGE[b.status] || 's-drafted'}`} style={{ marginLeft: 10 }}>{b.status}</span>
                <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{b.subject}</div>
              </div>
              <div className="mkt-card-actions">
                {b.status === 'draft' && <button className="btn" onClick={() => startEdit(b)}>Edit &amp; send</button>}
                {b.status === 'paused' && <button className="btn" title={b.error} onClick={() => startEdit(b)}>Inspect</button>}
                <button className="icon-btn" title="Delete" onClick={() => doDelete(b)}><Icon name="trash" size={14} /></button>
              </div>
            </div>
            {b.status === 'sending' && (
              <div className="send-progress" style={{ marginTop: 10 }}>
                <i style={{ width: `${pct}%` }} />
                <span className="send-progress-label">Sending {b.progress.done}/{b.progress.total}…</span>
              </div>
            )}
            {(b.status === 'sent' || s.accepted > 0) && (
              <div className="mkt-stats">
                {[['recipients', s.recipients], ['delivered', s.delivered], ['opened', s.opened],
                  ['clicked', s.clicked], ['bounced', s.bounced], ['unsubs', s.unsubs]].map(([k, v]) => (
                  <div key={k}><b>{v || 0}</b><span>{k}</span></div>
                ))}
              </div>
            )}
            {b.error && <div className="banner error" style={{ marginTop: 10, marginBottom: 0 }}>{b.error}</div>}
          </div>
        )
      })}
    </div>
  )
}
