import { useEffect, useState } from 'react'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'

// A publication is the thing a blast is an ISSUE OF: its knowledge block is the only
// set of claims a generated draft may state as fact, and its DO NOT lines are what
// stop one inventing a customer name. Three were seeded from the product docs so the
// blocks started true rather than as an empty box somebody fills with adjectives —
// but seeded is not the same as fixed, and until now there was no way to add a
// fourth or correct a line in an existing one.
const EMPTY = {
  name: '', product: '', description: '', voice: '', knowledge: '',
  from_address: '', reply_to: '',
  // Not edited here, but PUT sends the whole model and `audience` defaults to {} —
  // so it has to be carried through the form or saving a wording change would
  // silently clear the publication's audience preset.
  audience: {},
}

export default function Publications() {
  const [pubs, setPubs] = useState(null)
  const [editing, setEditing] = useState(null)   // publication id, or 'new'
  const [draft, setDraft] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)

  const load = () => api.listPublications().then(setPubs).catch(() => setPubs([]))
  useEffect(() => { load() }, [])

  const startNew = () => { setDraft(EMPTY); setEditing('new'); setMsg(null) }
  const startEdit = (p) => {
    setDraft({ ...EMPTY, ...p })
    setEditing(p.id); setMsg(null)
  }

  const save = async () => {
    if (!draft.name.trim()) { setMsg({ ok: false, text: 'A publication needs a name.' }); return }
    setBusy(true); setMsg(null)
    try {
      const body = {
        name: draft.name.trim(), product: draft.product.trim(),
        description: draft.description.trim(), voice: draft.voice.trim(),
        knowledge: draft.knowledge, from_address: draft.from_address.trim(),
        reply_to: draft.reply_to.trim(), audience: draft.audience || {},
      }
      if (editing === 'new') await api.createPublication(body)
      else await api.updatePublication(editing, body)
      setEditing(null); load()
    } catch (e) { setMsg({ ok: false, text: String(e.message).slice(0, 220) }) }
    finally { setBusy(false) }
  }

  const doDelete = async (p) => {
    setBusy(true)
    try { await api.deletePublication(p.id); setConfirmDel(null); load() }
    catch (e) { setMsg({ ok: false, text: String(e.message).slice(0, 220) }) }
    finally { setBusy(false) }
  }

  if (pubs === null) {
    return <div><Skeleton h={92} r={10} /><Skeleton h={92} r={10} style={{ marginTop: 14 }} /></div>
  }

  // ---------- editor ----------
  if (editing) {
    const isNew = editing === 'new'
    return (
      <div className="mkt">
        <button className="ghostlink" onClick={() => setEditing(null)}>← All publications</button>
        <div className="section-label" style={{ marginTop: 14 }}>
          {isNew ? 'New publication' : 'Edit publication'}
        </div>
        <div className="pub-form">
          <label className="pub-lbl">Name
            <input className="field-input" value={draft.name} placeholder="e.g. The Safety Brief"
              onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <span className="pub-help">Recipients see this. It also names each issue: “{draft.name || 'Name'} #1”.</span>
          </label>

          <label className="pub-lbl">Product it speaks for
            <input className="field-input" value={draft.product} placeholder="e.g. KnowDoc AI"
              onChange={(e) => setDraft({ ...draft, product: e.target.value })} />
          </label>

          <label className="pub-lbl">Who it's for
            <input className="field-input" value={draft.description}
              placeholder="e.g. Back-office and compliance leads at carriers, brokers and 3PLs"
              onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            <span className="pub-help">Written to these people, not to “business leaders”.</span>
          </label>

          <label className="pub-lbl">Voice
            <input className="field-input" value={draft.voice}
              placeholder="e.g. Concrete and operational. Talks about packets and exceptions, not 'digital transformation'."
              onChange={(e) => setDraft({ ...draft, voice: e.target.value })} />
          </label>

          {/* The one field that actually matters. Everything else is presentation. */}
          <label className="pub-lbl">What issues may state as fact
            <textarea className="field-input pub-knowledge" rows={12} value={draft.knowledge}
              placeholder={'What this product genuinely does, in plain sentences.\n\nThen the limits, on their own line:\nDO NOT claim: customer names, percentages, ROI figures — none are verified.\nDO NOT pitch features that are not shipped.'}
              onChange={(e) => setDraft({ ...draft, knowledge: e.target.value })} />
            <span className="pub-help">
              The generator may state <b>nothing</b> about the product that isn't written here, and
              obeys every <code>DO NOT</code> line. An empty block means it makes no product claim
              at all — safe, and usually not what you want.
            </span>
          </label>

          <div className="pub-two">
            <label className="pub-lbl">From address
              <input className="field-input" value={draft.from_address}
                placeholder="Sid Singh &lt;news@knowella.com&gt;"
                onChange={(e) => setDraft({ ...draft, from_address: e.target.value })} />
              <span className="pub-help">Must be verified in Postmark. Blank uses MARKETING_FROM.</span>
            </label>
            <label className="pub-lbl">Reply-To
              <input className="field-input" value={draft.reply_to} placeholder="sid@knowella.ca"
                onChange={(e) => setDraft({ ...draft, reply_to: e.target.value })} />
              <span className="pub-help">Where replies land. A reply to a newsletter is warm inbound.</span>
            </label>
          </div>

          {msg && <div className="banner error">{msg.text}</div>}
          <div className="pub-actions">
            <button className="btn" onClick={() => setEditing(null)}>Cancel</button>
            <button className="btn primary" disabled={busy || !draft.name.trim()} onClick={save}>
              {busy ? <><span className="spinner" /> Saving…</> : (isNew ? 'Create publication' : 'Save changes')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ---------- list ----------
  return (
    <div className="mkt">
      <div className="mkt-head">
        <div>
          <div className="section-label" style={{ marginBottom: 4 }}>Marketing · publications</div>
          <p className="muted" style={{ margin: 0, maxWidth: 620 }}>
            A blast is an issue of a publication. The publication decides who it's written for,
            what it may claim, and which address it comes from.
          </p>
        </div>
        <button className="btn primary" onClick={startNew}><Icon name="plus" size={15} /> New publication</button>
      </div>

      {msg && <div className="banner error">{msg.text}</div>}

      {pubs.length === 0 ? (
        <div className="empty">No publications yet. Create one before writing an issue — without it
          a draft has nothing that says what it may claim.</div>
      ) : pubs.map((p) => (
        <div className="pub-card" key={p.id}>
          <div className="pub-card-main">
            <div className="pub-card-top">
              <b>{p.name}</b>
              <span className="pub-badge">{p.product || 'no product named'}</span>
              <span className="muted" style={{ fontSize: 12 }}>
                {p.issues ? `${p.issues} ${p.issues === 1 ? 'issue' : 'issues'} sent` : 'no issues yet'}
                {' · next #'}{(p.issues || 0) + 1}
              </span>
            </div>
            <div className="muted" style={{ fontSize: 13 }}>{p.description || '—'}</div>
            <div className="pub-from">
              {p.from_address || <span className="muted">falls back to MARKETING_FROM</span>}
              {p.reply_to && <> · replies to {p.reply_to}</>}
            </div>
            {!p.knowledge?.trim() && (
              <div className="pub-warn">
                No knowledge block — issues of this publication can make no product claim at all.
              </div>
            )}
          </div>
          <div className="pub-card-actions">
            <button className="btn" onClick={() => startEdit(p)}>Edit</button>
            <button className="btn reject" onClick={() => setConfirmDel(p)}><Icon name="x" size={14} /></button>
          </div>
          {confirmDel?.id === p.id && (
            <div className="bulk-confirm danger" style={{ gridColumn: '1 / -1' }}>
              <div className="bulk-confirm-text">
                Delete <b>{p.name}</b>?{' '}
                {p.issues > 0
                  ? <>Its {p.issues} sent {p.issues === 1 ? 'issue stays' : 'issues stay'} in the record,
                      but {p.issues === 1 ? 'it loses' : 'they lose'} the publication{' '}
                      {p.issues === 1 ? 'it was' : 'they were'} an issue of, and issue numbering
                      restarts if you recreate it.</>
                  : <>Nothing has been sent under it, so nothing is lost.</>}
              </div>
              <div className="bulk-confirm-actions">
                <button className="btn" onClick={() => setConfirmDel(null)}>Cancel</button>
                <button className="btn reject" disabled={busy} onClick={() => doDelete(p)}>
                  {busy ? <><span className="spinner spinner-dark" /> Deleting…</> : 'Delete'}
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
