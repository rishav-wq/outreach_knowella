import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'

// Right slideout: full detail for one lead — email, facts, sending info, actions.
export default function Drawer({ campaign, leadKey, onClose, onChange, onDecided }) {
  const [d, setD] = useState(null)
  const [editing, setEditing] = useState(false)
  const [factsOpen, setFactsOpen] = useState(true)
  const [eSubject, setESubject] = useState('')
  const [eBody, setEBody] = useState('')
  const [emailEdit, setEmailEdit] = useState(false)
  const [eEmail, setEEmail] = useState('')
  const [emailErr, setEmailErr] = useState('')

  useEffect(() => {
    setD(null); setEditing(false); setFactsOpen(true); setEmailEdit(false); setEmailErr('')
    api.getLead(campaign, leadKey).then(setD).catch(() => {})
  }, [campaign, leadKey])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const decide = async (decision) => {
    await api.decide(campaign, leadKey, decision)
    onChange && onChange()
    if (onDecided) onDecided(leadKey)
    else setD((p) => ({ ...p, decision: decision === 'approve' ? 'approved' : 'rejected' }))
  }
  const startEdit = () => { setESubject(d.subject); setEBody(d.body); setEditing(true) }
  const saveEdit = async () => {
    await api.editEmail(campaign, leadKey, eSubject, eBody)
    setD((p) => ({ ...p, subject: eSubject, body: eBody, edited: true })); setEditing(false); onChange && onChange()
  }

  const saveEmail = async () => {
    setEmailErr('')
    try {
      const r = await api.setLeadEmail(campaign, leadKey, eEmail)
      setD((p) => ({ ...p, email: r.email, verify: r.verify }))
      setEmailEdit(false)
      onChange && onChange()
    } catch (e) {
      setEmailErr(/valid email/.test(String(e.message)) ? 'That doesn’t look like a valid email address.' : `Could not save: ${e.message}`)
    }
  }

  // One answer to "if I approve this, will it actually go?"
  const readiness = () => {
    if (!d) return null
    if (!d.email) return { kind: 'warn', text: 'Won’t send — no email address.' }
    if (d.require_deliverable && d.verify !== 'deliverable') {
      return { kind: 'warn', text: `Held until verified — this campaign only sends to verified addresses (currently ${d.verify || 'unchecked'}).` }
    }
    return { kind: 'ok', text: 'Ready to send' }
  }
  const ready = readiness()
  const showHint = !!onDecided && !d?.decision

  return (
    <>
      <motion.div className="drawer-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
      <motion.aside className="drawer" role="dialog" aria-label="Lead detail"
        initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
        transition={{ type: 'spring', stiffness: 380, damping: 38 }}>
        {!d ? (
          <div className="drawer-pad"><Skeleton w="60%" h={20} /><Skeleton w="100%" h={14} style={{ marginTop: 22 }} /><Skeleton w="90%" h={14} style={{ marginTop: 8 }} /></div>
        ) : (
          <>
            <div className="drawer-head">
              <div className="drawer-who">
                <div className="avatar">{(d.name || '?').slice(0, 1)}</div>
                <div>
                  <div className="drawer-name">{d.name}</div>
                  <div className="drawer-co">{d.company}</div>
                  <div className="drawer-sub">
                    {d.source && <span className="src-tag">{d.source}</span>}
                    {d.verdict && <span className={`badge v-${d.verdict}`}>{d.verdict}</span>}
                    {d.decision && <span className={`badge s-${d.decision}`}>{d.decision}</span>}
                    {d.edited && <span className="badge s-drafted">edited</span>}
                  </div>
                </div>
              </div>
              <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={18} /></button>
            </div>

            <div className="drawer-body">
              <div className="drawer-section">
                <div className="drawer-label">Draft email</div>
                {editing ? (
                  <div className="edit-form">
                    <input className="edit-subject" value={eSubject} onChange={(e) => setESubject(e.target.value)} placeholder="Subject" />
                    <textarea className="edit-body" value={eBody} onChange={(e) => setEBody(e.target.value)} rows={12} />
                    <div className="edit-actions">
                      <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
                      <button className="btn primary" onClick={saveEdit}>Save changes</button>
                    </div>
                  </div>
                ) : d.subject ? (
                  <div className="drawer-email">
                    <div className="subject">{d.subject}</div>
                    <pre className="body">{d.body}</pre>
                  </div>
                ) : <div className="muted">No draft yet. Run the pipeline to research this lead and write one.</div>}
              </div>

              {d.facts?.length > 0 && (
                <div className="drawer-section">
                  <button className="facts-toggle" onClick={() => setFactsOpen((o) => !o)}>
                    <span>Grounded in {d.facts.length} verified facts</span>
                    <Icon name="chevron" size={15} className={factsOpen ? 'rot' : ''} />
                  </button>
                  {factsOpen && (
                    <ul className="drawer-facts">
                      {d.facts.map((f, i) => (
                        <li key={i}>
                          <span>{f.claim}</span>
                          {f.source_url && <a href={f.source_url} target="_blank" rel="noreferrer" aria-label="Open source"><Icon name="link" size={12} /></a>}
                          <span className="src">{f.source_type}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className="drawer-section">
                <div className="drawer-label">Send readiness</div>
                <div className={`ready ${ready.kind}`}>
                  <span className={`dot ${ready.kind === 'ok' ? 'd-ok' : 'd-held'}`} />
                  <div className="ready-main">
                    <div className="ready-text">{ready.text}</div>
                    {d.email && !emailEdit && (
                      <div className="ready-email">
                        {d.email}
                        {d.verify_active && <span className={`badge ${d.verify === 'deliverable' ? 's-approved' : d.verify === 'undeliverable' ? 's-invalid' : 's-held'}`}>{d.verify || 'unchecked'}</span>}
                        <button className="linklike ready-edit" onClick={() => { setEEmail(d.email); setEmailEdit(true) }}>change</button>
                      </div>
                    )}
                    {(!d.email || emailEdit) && (
                      <div className="ready-form">
                        <input className="field-input" type="email" placeholder="name@company.com"
                          value={eEmail} onChange={(e) => setEEmail(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && saveEmail()} />
                        <button className="btn" onClick={saveEmail}>Save email</button>
                        {emailEdit && <button className="icon-btn" onClick={() => setEmailEdit(false)} aria-label="Cancel"><Icon name="x" size={14} /></button>}
                      </div>
                    )}
                    {emailErr && <div className="ready-err">{emailErr}</div>}
                  </div>
                </div>
              </div>
            </div>

            {d.subject && !editing && (
              <div className="drawer-actions">
                {showHint && <span className="hint">Esc closes · approving opens the next draft</span>}
                <button className="btn" onClick={startEdit}>Edit</button>
                <button className="btn reject" onClick={() => decide('reject')}><Icon name="x" size={15} /> Reject</button>
                <button className="btn approve" onClick={() => decide('approve')}><Icon name="check" size={15} /> Approve</button>
              </div>
            )}
          </>
        )}
      </motion.aside>
    </>
  )
}
