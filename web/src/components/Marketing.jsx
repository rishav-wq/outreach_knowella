import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'

// The marketing engine's cockpit: 1:many blasts (announcements, newsletters) to
// live Library segments via Postmark — one message, one human approval, real
// per-person stats from webhooks. The counterpart to Review's one-lead-at-a-time.

const STATUS_BADGE = { draft: 's-drafted', sending: 's-queued', sent: 's-approved', paused: 's-invalid' }

const EMPTY = { name: '', subject: '', body: '', publication_id: '', audience: { topics: [], statuses: [], exclude_sent: true, engagement: '', subscribers_only: false } }

export default function Marketing() {
  const [blasts, setBlasts] = useState(null)
  const [view, setView] = useState('list')          // 'list' | 'edit'
  const [draft, setDraft] = useState(EMPTY)
  const [draftId, setDraftId] = useState(null)      // editing an existing draft
  const [topics, setTopics] = useState([])
  const [audiences, setAudiences] = useState([])
  const [pubs, setPubs] = useState([])
  const [question, setQuestion] = useState('')
  const [gen, setGen] = useState(null)     // {used, omitted} from the last draft
  const [conn, setConn] = useState(null)            // {connected, from, stream}
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
    api.listPublications().then(setPubs).catch(() => {})
    api.getMarketingStatus().then(setConn).catch(() => {})
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
  // A greyed-out button with no reason is a dead end. Name the missing field so the
  // fix is one click away instead of a guess.
  const blocker = draft.name.trim() ? (draft.subject.trim() ? (draft.body.trim() ? '' : 'a body')
    : 'a subject line') : 'an internal name'

  // save (create or update) and return the id — test/send both go through here so
  // what you test is always exactly what's stored
  const save = async () => {
    if (draftId) { await api.updateBlast(draftId, draft); return draftId }
    const r = await api.createBlast(draft)
    setDraftId(r.id)
    return r.id
  }

  // Drafting is bounded by the publication's knowledge block, so a publication is
  // required — without one there is nothing the model may state as fact.
  const doGenerate = async () => {
    setBusy('gen'); setMsg(null)
    try {
      const r = await api.generateIssue({
        publication_id: draft.publication_id,
        question: question.trim(),
        audience: draft.audience,
      })
      // Name it too. Generating subject and body but leaving the internal name blank
      // left the form looking finished while the send buttons stayed disabled.
      const p = pubs.find((x) => x.id === draft.publication_id)
      const auto = p ? `${p.name} #${(p.issues || 0) + 1}` : r.subject
      setDraft((d) => ({ ...d, subject: r.subject, body: r.body, name: d.name.trim() || auto }))
      // If it had to pick the question itself, show which — an issue answering an
      // unseen question is unreviewable, and a bad pick is the first thing to fix.
      if (r.question) setQuestion(r.question)
      setGen({ used: r.used || [], omitted: r.omitted || [], picked: !!r.question_was_picked })
    } catch (e) { setMsg({ ok: false, text: String(e.message).slice(0, 240) }) }
    finally { setBusy('') }
  }

  // Questions the publication could answer. Explicitly a stopgap: these are inferred
  // from the product knowledge, and content written from what you sell is weaker than
  // content written from what buyers asked. The label says so.
  const [ideas, setIdeas] = useState(null)
  const doSuggest = async () => {
    setBusy('ideas'); setMsg(null)
    try {
      const r = await api.suggestQuestions(draft.publication_id)
      setIdeas(r.questions || [])
    } catch (e) { setMsg({ ok: false, text: String(e.message).slice(0, 240) }) }
    finally { setBusy('') }
  }

  const doTest = async () => {
    setBusy('test'); setMsg(null)
    try {
      const id = await save()
      const r = await api.testBlast(id, testTo.trim())
      const failed = (r.failed || []).length
      setMsg({
        ok: failed === 0,
        text: `Test sent to ${r.sent} ${r.sent === 1 ? 'address' : 'addresses'}`
          + ` (rendered with ${r.rendered_for}'s details).`
          + (failed ? ` ${failed} rejected: ${r.failed.join('; ').slice(0, 160)}` : '')
          + ` A real send would reach ${r.audience_count} people.`,
      })
      load()
    } catch (e) { setMsg({ ok: false, text: `Test failed: ${String(e.message).slice(0, 220)}` }) }
    finally { setBusy('') }
  }

  // Batch size for the send. Warming a list beats discovering a bad from-address,
  // a broken merge field or a complaint rate on all 211 at once — Postmark suspends
  // broadcast senders over complaints, and that takes the sales domain with it.
  const [batch, setBatch] = useState(5)
  const doSend = async (limit) => {
    const total = preview?.count ?? 0
    const n = limit ? Math.min(limit, total) : total
    const rest = limit ? ` The remaining ${Math.max(0, total - n)} stay unsent until you send again.` : ''
    if (!window.confirm(`Send this blast to ${n} ${n === 1 ? 'person' : 'people'} via Postmark?${rest} Every message carries a one-click unsubscribe.`)) return
    setBusy('send'); setMsg(null)
    try {
      const id = await save()
      const r = await api.sendBlast(id, limit)
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

  // Postmark is the only way anything leaves this page. Discovering it's unwired
  // after writing a full issue wastes the work — say it before the compose box.
  const unwired = conn && !conn.connected ? 'the Postmark server token is missing'
    : conn && !conn.from ? 'MARKETING_FROM is not set, so there is no address to send from' : ''
  const wiring = unwired ? (
    <div className="send-blocked" style={{ marginTop: 0, marginBottom: 14 }}>
      <b>Marketing can't send yet</b> — {unwired}. Add it to the server's <code>.env</code> and
      restart. Drafts still save; nothing leaves, including tests.
    </div>
  ) : conn?.connected && conn.unsub_synced === false ? (
    <div className="send-blocked" style={{ marginTop: 0, marginBottom: 14 }}>
      <b>Unsubscribes won't reach this app</b> — Postmark has no SubscriptionChange
      webhook on the <code>{conn.stream}</code> stream. It will still stop the newsletter,
      but someone who opts out keeps getting cold sales mail until you add the webhook.
    </div>
  ) : null

  // ---------- composer ----------
  if (view === 'edit') {
    return (
      <div className="mkt">
        <button className="ghostlink" onClick={() => setView('list')}>← All blasts</button>
        {wiring}
        <div className="mkt-grid">
          <div className="mkt-main">
            <div className="section-label">Compose</div>

            {/* Drafting needs a publication, because the publication is what says
                which claims are true. The question is the strongest input there is —
                an issue that answers something a buyer actually asked beats one that
                announces something nobody wondered about. */}
            <div className="gen-row">
              <input className="field-input" value={question} placeholder="What question should this issue answer? (optional)"
                onChange={(e) => setQuestion(e.target.value)} />
              <button className="btn gen-btn" disabled={!draft.publication_id || busy !== ''}
                onClick={doGenerate}
                title={draft.publication_id ? 'Bounded by the knowledge block of this publication'
                  : 'Pick a publication first — it decides what may be claimed'}>
                {busy === 'gen' ? <><span className="spinner spinner-dark" /> Writing…</> : '✦ Write with AI'}
              </button>
            </div>
            {draft.publication_id && (
              <div className="idea-row">
                <button className="ghostlink" disabled={busy !== ''} onClick={doSuggest}>
                  {busy === 'ideas' ? 'Thinking…' : ideas ? '↻ Other questions' : 'Not sure what to ask?'}
                </button>
                {ideas && (
                  <div className="ideas">
                    {ideas.map((q, i) => (
                      <button key={i} className="idea" onClick={() => { setQuestion(q); setIdeas(null) }}>{q}</button>
                    ))}
                    <div className="muted" style={{ fontSize: 11.5 }}>
                      Guessed from the knowledge block. A question a buyer actually asked beats
                      all four of these — those come from the Backlog.
                    </div>
                  </div>
                )}
              </div>
            )}
            {gen && (
              <div className="gen-note">
                {gen.picked && (
                  <div style={{ marginBottom: 4 }}>
                    <b>Chose the question above</b> — you left it blank. Edit it and write again
                    if it picked the wrong one.
                  </div>
                )}
                <div><b>Leaned on:</b> {gen.used.length ? gen.used.join(' · ') : '—'}</div>
                {gen.omitted.length > 0 && (
                  <div className="gen-omit"><b>Left out for lack of a source:</b> {gen.omitted.join(' · ')}</div>
                )}
                <div className="muted">Read it before you send it — it drafts, you decide.</div>
              </div>
            )}

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
            <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>
              Formatting: <code>**bold**</code>, <code>- bullets</code>, <code>[text](url)</code> and bare
              links. Nothing else — no images or buttons, because looking like bulk mail is what costs opens.
            </div>

            {blocker && (
              <div className="send-blocked">Nothing sends yet — this issue still needs {blocker}.</div>
            )}
            <div className="mkt-actions">
              <div className="ready-form" style={{ margin: 0 }}>
                <input className="field-input"
                  placeholder="you@gmail.com, colleague@knowella.com — up to 10"
                  value={testTo} onChange={(e) => setTestTo(e.target.value)} style={{ width: 330 }} />
                <button className="btn" disabled={!complete || !testTo.includes('@') || busy !== ''} onClick={doTest}>
                  {busy === 'test' ? <><span className="spinner spinner-dark" /> Sending…</>
                    : `Send test to ${testTo.split(/[,;\s]+/).filter((a) => a.includes('@')).length || 1}`}
                </button>
              </div>
              <div className="blast-send">
                <div className="blast-batch">
                  <span>Warm up with</span>
                  <input className="field-input" type="number" min="1" max={preview?.count || 1}
                    value={batch} onChange={(e) => setBatch(Math.max(1, Number(e.target.value) || 1))} />
                  <button className="btn approve" disabled={!complete || busy !== '' || !preview?.count}
                    onClick={() => doSend(batch)}>
                    {busy === 'send' ? <><span className="spinner" /> Starting…</> : `Send to ${Math.min(batch, preview?.count || 0)} first`}
                  </button>
                </div>
                <button className="btn blast-all" disabled={!complete || busy !== '' || !preview?.count}
                  onClick={() => doSend(0)}
                  title={!preview?.count ? 'The audience is empty' : 'Sends to everyone who has not had it yet'}>
                  or send to all {preview?.count ?? '…'}
                </button>
              </div>
            </div>
            {msg && <div className={`banner ${msg.ok ? '' : 'error'}`} style={{ marginTop: 12 }}>{msg.text}</div>}
          </div>

          <aside className="mkt-side">
            {/* The publication decides what this issue may claim and who it goes to.
                It sits above the audience because picking it usually answers both. */}
            <div className="section-label">Publication</div>
            <select className="src-select" style={{ width: '100%', marginBottom: 6 }}
              value={draft.publication_id || ''}
              onChange={(e) => {
                const pub = pubs.find((x) => x.id === e.target.value)
                setDraft((d) => ({
                  ...d,
                  publication_id: e.target.value,
                  audience: pub && Object.keys(pub.audience || {}).length
                    ? { ...d.audience, ...pub.audience } : d.audience,
                }))
              }}>
              <option value="">One-off — no publication</option>
              {pubs.map((p) => (
                <option key={p.id} value={p.id}>{p.name}{p.issues ? ` · ${p.issues} issues` : ''}</option>
              ))}
            </select>
            {(() => {
              const pub = pubs.find((x) => x.id === draft.publication_id)
              if (!pub) return null
              return (
                <div className="pub-note">
                  <b>{pub.product}</b> · next issue #{(pub.issues || 0) + 1}
                  {pub.knowledge && (
                    <details className="pub-know">
                      <summary>What this issue may state as fact</summary>
                      <pre>{pub.knowledge}</pre>
                    </details>
                  )}
                </div>
              )
            })()}

            <div className="section-label" style={{ marginTop: 16 }}>Audience — live from the Library</div>
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
            {/* Consent first. Everything below narrows the Library — people we FOUND.
                This one switches to the people who ASKED, which is the only audience
                a newsletter may go to, so it sits above the rest and overrides them. */}
            <label className="use-ai-toggle mkt-optin" style={{ marginBottom: 12 }}>
              <input type="checkbox" checked={!!draft.audience.subscribers_only}
                onChange={(e) => setDraft({ ...draft, audience: { ...draft.audience, subscribers_only: e.target.checked } })} />
              <span><b>Only confirmed subscribers</b>
                <span className="muted"> — people who opted in and clicked the confirmation link.
                  The only audience safe for a newsletter; ignores the filters below.</span></span>
            </label>

            <label className="use-ai-toggle" style={{ marginBottom: 12, opacity: draft.audience.subscribers_only ? 0.45 : 1 }}>
              <input type="checkbox" disabled={!!draft.audience.subscribers_only}
                checked={!!draft.audience.exclude_sent}
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
      {wiring}
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
