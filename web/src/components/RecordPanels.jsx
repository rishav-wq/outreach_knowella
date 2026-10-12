import { useEffect, useState } from 'react'
import * as api from '../api'
import SlideOut from './SlideOut'
import Skeleton from './Skeleton'
import Timeline, { NoteComposer, REPLY_LABEL } from './Timeline'
import { avatarTint, initials } from './avatar'
import { isAdmin } from '../me'

// The lead and company panels, shown in the shared 84vw slide-out. A lead links to its
// company and a company to its leads; the panel keeps a back trail between them.

const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '')
const fmtDate = (s) => {
  if (!s) return ''
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}
const STATUS = { new: 'Not drafted', queued: 'Queued', drafted: 'Drafted', sent: 'Sent', bounced: 'Bounced', suppressed: 'Suppressed', excluded: 'Not a fit', rejected: 'Rejected', error: 'Error' }

export function StageChip({ stage, auto }) {
  const k = String(stage || '').toLowerCase().replace(/[^a-z]+/g, '-')
  return (
    <span className={`stage-chip st-${k} ${auto ? 'auto' : ''}`}
      title={auto ? 'Automatic: worked out from what has happened. Pick a stage to set it by hand.' : 'Set by hand'}>
      {stage}
    </span>
  )
}

function StageStrip({ stages, current }) {
  const at = stages.indexOf(current)
  return (
    <ol className="rec-strip" aria-label="Stage">
      {stages.map((s, i) => (
        <li key={s} className={i < at ? 'done' : i === at ? 'now' : 'next'} aria-current={i === at ? 'step' : undefined}>{s}</li>
      ))}
      {at === -1 && current && <li className="now">{current}</li>}
    </ol>
  )
}

function OwnerControl({ me, users, value, valueName, onChange }) {
  if (!isAdmin(me) || !users) {
    return <span className="rec-owner">{valueName || 'Admins'}</span>
  }
  const eligible = users.filter((u) => u.active && (u.role === 'sales' || u.role === 'admin'))
  return (
    <select className="field-input rec-select" aria-label="Owner" value={value || ''} onChange={(e) => onChange(e.target.value)}>
      <option value="">Admins only</option>
      {value && !eligible.some((u) => u.id === value) && <option value={value}>{valueName || value}</option>}
      {eligible.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
    </select>
  )
}

function Section({ title, children, action }) {
  return (
    <section className="rec-sec">
      <div className="rec-sec-h"><h3>{title}</h3>{action}</div>
      {children}
    </section>
  )
}

// --- a lead -----------------------------------------------------------------------
function PersonPanel({ id, me, meta, users, onOpenCompany, onChanged, onDeleted }) {
  const [p, setP] = useState(null)
  const [err, setErr] = useState('')
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({})
  const load = () => api.getPerson(id).then((d) => { setP(d); setErr('') }).catch((e) => setErr(api.errorText(e)))
  useEffect(() => { load() }, [id])  // eslint-disable-line react-hooks/exhaustive-deps
  const patch = async (body) => {
    setErr('')
    try { await api.updatePerson(id, body); await load(); onChanged() } catch (e) { setErr(api.errorText(e)) }
  }
  if (err && !p) return <div className="rec"><div className="banner error">{err}</div></div>
  if (!p) return <div className="rec"><Skeleton h={28} w="40%" /><Skeleton h={300} r={10} style={{ marginTop: 16 }} /></div>

  const startEdit = () => {
    setForm({ first_name: p.first_name, last_name: p.last_name, title: p.title, phones: p.phones.join(', '), linkedin_url: p.linkedin_url })
    setEditing(true)
  }
  const saveEdit = async () => {
    await patch({ ...form, phones: form.phones.split(',').map((x) => x.trim()).filter(Boolean) })
    setEditing(false)
  }
  const toggleInterest = (i) => patch({ interests: p.interests.includes(i) ? p.interests.filter((x) => x !== i) : [...p.interests, i] })
  const remove = async () => {
    const n = p.enrollments.length
    if (!window.confirm(n ? `Delete ${p.name} and their history in ${n} campaign${n === 1 ? '' : 's'}? This can't be undone.`
      : `Delete ${p.name}? This can't be undone.`)) return
    try { await api.deletePerson(id); onDeleted() } catch (e) { setErr(api.errorText(e)) }
  }
  const li = p.linkedin_url ? `https://www.${p.linkedin_url}` : ''
  const loc = [p.apollo.city, p.apollo.state, p.apollo.country].filter(Boolean).join(', ')
  return (
    <div className="rec">
      <header className="rec-head">
        <span className="avatar lg" style={avatarTint(p.name)}>{initials(p.name)}</span>
        <div className="rec-title">
          <h2>{p.name || p.email}</h2>
          <div className="muted rec-sub">
            {p.title && <span>{p.title}</span>}
            {p.company
              ? <button className="linklike inline" onClick={() => onOpenCompany(p.company.id)}>{p.company.name || p.company_name}</button>
              : (p.company_name && <span>{p.company_name}</span>)}
            {p.email && <span>{p.email}</span>}
          </div>
          {p.suppressed && <div className="rec-dnc">On the do-not-contact list: never emailed again.</div>}
        </div>
        <div className="rec-controls">
          <label>Owner <OwnerControl me={me} users={users} value={p.owner} valueName={p.owner_name} onChange={(v) => patch({ owner: v })} /></label>
          <label>Stage
            <select className="field-input rec-select" value={p.stage_auto ? '' : p.stage} onChange={(e) => patch({ stage: e.target.value })}>
              <option value="">Automatic: {p.stage_derived}</option>
              {meta.lead_stages.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        </div>
      </header>
      <StageStrip stages={meta.lead_open} current={p.stage} />
      {err && <div className="banner error">{err}</div>}
      <div className="rec-body">
        <aside className="rec-side">
          <Section title="Details" action={!editing && <button className="linklike" onClick={startEdit}>Edit</button>}>
            {editing ? (
              <div className="rec-form">
                {[['first_name', 'First name'], ['last_name', 'Last name'], ['title', 'Title'], ['phones', 'Phones (comma-separated)'], ['linkedin_url', 'LinkedIn']].map(([k, l]) => (
                  <label key={k}>{l}<input className="field-input" value={form[k] || ''} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>
                ))}
                <div className="rec-form-row">
                  <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
                  <button className="btn primary" onClick={saveEdit}>Save</button>
                </div>
              </div>
            ) : (
              <dl className="rec-dl">
                <dt>Email</dt><dd>{p.email || '—'}{p.emails.length > 0 && <div className="muted">also {p.emails.join(', ')}</div>}</dd>
                <dt>Phone</dt><dd>{p.phones.length ? p.phones.join(', ') : '—'}</dd>
                <dt>LinkedIn</dt><dd>{li ? <a href={li} target="_blank" rel="noopener noreferrer">{p.linkedin_url.replace('linkedin.com/in/', '')} ↗</a> : '—'}</dd>
                <dt>Source</dt><dd>{p.source.type || '—'}{p.source.campaign ? ` · ${p.source.campaign}` : ''}</dd>
                <dt>Sourced by</dt><dd>{p.sourced_by.label || '—'}{p.sourced_by.at ? ` · ${fmtDate(p.sourced_by.at)}` : ''}</dd>
                {p.not_fit_reason && <><dt>Not a fit</dt><dd>{p.not_fit_reason}</dd></>}
              </dl>
            )}
          </Section>
          <Section title="Interests">
            {Object.entries(meta.interests).map(([group, list]) => (
              <div key={group} className="rec-int">
                <div className="rec-int-h">{group}</div>
                <div className="chip-row">
                  {list.map((i) => (
                    <button key={i} type="button" className={`chip ${p.interests.includes(i) ? 'on' : ''}`} aria-pressed={p.interests.includes(i)}
                      onClick={() => toggleInterest(i)}>{i}</button>
                  ))}
                </div>
              </div>
            ))}
          </Section>
          <Section title={`Campaigns · ${p.enrollments.length}`}>
            {p.enrollments.length === 0 ? <div className="muted">Not in any campaign.</div> : (
              <ul className="rec-list">
                {p.enrollments.map((e) => (
                  <li key={e.key}>
                    <b>{e.campaign}</b>{!e.yours && <span className="muted"> (someone else's)</span>}
                    <div className="muted">
                      {STATUS[e.status] || e.status}
                      {e.sent && ` · sent ${fmtDate(e.sent)}`}
                      {e.replied && ` · replied${e.reply_label ? ` (${REPLY_LABEL[e.reply_label] || e.reply_label})` : ''}`}
                      {e.meeting && ' · meeting booked'}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Section>
          {Object.keys(p.apollo).length > 0 && (
            <Section title="From Apollo">
              <dl className="rec-dl">
                {p.apollo.headline && <><dt>Headline</dt><dd>{p.apollo.headline}</dd></>}
                {p.apollo.seniority && <><dt>Seniority</dt><dd>{p.apollo.seniority}</dd></>}
                {p.apollo.departments && <><dt>Department</dt><dd>{p.apollo.departments.join(', ').replace(/_/g, ' ')}</dd></>}
                {loc && <><dt>Location</dt><dd>{loc}</dd></>}
                {p.apollo.time_zone && <><dt>Time zone</dt><dd>{p.apollo.time_zone}</dd></>}
              </dl>
              {p.apollo.employment_history && (
                <ul className="rec-list rec-jobs">
                  {p.apollo.employment_history.map((h, i) => (
                    <li key={i}><b>{h.title || '—'}</b> · {h.company}
                      <div className="muted">{(h.start || '').slice(0, 7)}{' – '}{h.current ? 'now' : (h.end || '').slice(0, 7)}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          )}
          <div className="rec-danger">
            <button className="linklike danger" onClick={remove}
              disabled={p.enrollments.length > 0 && !isAdmin(me)}
              title={p.enrollments.length > 0 && !isAdmin(me) ? 'In a campaign: remove them from it first, or ask an admin' : ''}>
              Delete this lead
            </button>
          </div>
        </aside>
        <section className="rec-main" aria-label="Activity">
          <NoteComposer onSave={async (b) => { await api.addPersonNote(id, b); await load(); onChanged() }} />
          <Timeline items={p.timeline} me={me} onChanged={() => { load(); onChanged() }} />
        </section>
      </div>
    </div>
  )
}

// --- a company ----------------------------------------------------------------------
function CompanyPanel({ id, me, meta, users, onOpenPerson, onChanged }) {
  const [c, setC] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api.getCompany(id).then((d) => { setC(d); setErr('') }).catch((e) => setErr(api.errorText(e)))
  useEffect(() => { load() }, [id])  // eslint-disable-line react-hooks/exhaustive-deps
  const patch = async (body) => {
    setErr('')
    try { await api.updateCompany(id, body); await load(); onChanged() } catch (e) { setErr(api.errorText(e)) }
  }
  if (err && !c) return <div className="rec"><div className="banner error">{err}</div></div>
  if (!c) return <div className="rec"><Skeleton h={28} w="40%" /><Skeleton h={300} r={10} style={{ marginTop: 16 }} /></div>
  const canEdit = isAdmin(me) || c.owner === me?.id
  const loc = [c.city, c.state, c.country].filter(Boolean).join(', ')
  const site = safeUrl(c.website_url) || (c.domain ? `https://${c.domain}` : '')
  const li = safeUrl(c.linkedin_url)
  return (
    <div className="rec">
      <header className="rec-head">
        <span className="avatar lg sq" style={avatarTint(c.name)}>{initials(c.name)}</span>
        <div className="rec-title">
          <h2>{c.name || c.domain}</h2>
          <div className="muted rec-sub">
            {site && <a href={site} target="_blank" rel="noopener noreferrer">{c.domain || site} ↗</a>}
            {[c.industry, c.employees ? `${c.employees.toLocaleString()} people` : '', loc].filter(Boolean).map((x) => <span key={x}>{x}</span>)}
          </div>
        </div>
        <div className="rec-controls">
          <label>Owner <OwnerControl me={me} users={users} value={c.owner} valueName={c.owner_name} onChange={(v) => patch({ owner: v })} /></label>
          <label>Stage
            <select className="field-input rec-select" disabled={!canEdit} value={c.stage_auto ? '' : c.stage}
              title={canEdit ? '' : "Only the company's owner or an admin can change it"}
              onChange={(e) => patch({ stage: e.target.value })}>
              <option value="">Automatic: {c.stage_derived}</option>
              {meta.company_stages.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        </div>
      </header>
      <StageStrip stages={meta.company_open} current={c.stage} />
      {err && <div className="banner error">{err}</div>}
      <div className="rec-body">
        <aside className="rec-side">
          <Section title={`Contacts · ${c.contacts.length}`}>
            {c.contacts.length === 0 && <div className="muted">None of yours here.</div>}
            <ul className="rec-list">
              {c.contacts.map((p) => (
                <li key={p.id}>
                  <div className="rec-contact">
                    <button className="linklike inline" onClick={() => onOpenPerson(p.id)}><b>{p.name || p.email}</b></button>
                    <StageChip stage={p.stage} auto={p.stage_auto} />
                  </div>
                  <div className="muted">{p.title || '—'}{p.emails_sent ? ` · emailed in ${p.emails_sent} campaign${p.emails_sent === 1 ? '' : 's'}` : ' · not emailed yet'}{p.replied ? ' · replied' : ''}</div>
                </li>
              ))}
            </ul>
            {c.others.length > 0 && (
              <div className="rec-others">
                Also here: {c.others.map((o) => `${o.count} ${o.count === 1 ? 'lead' : 'leads'} owned by ${o.owner}`).join(', ')}.
                {!isAdmin(me) && ' Ask them or an admin before reaching out.'}
              </div>
            )}
          </Section>
          <Section title="Account">
            <div className="rec-form compact">
              <label>Tier
                <select className="field-input" disabled={!canEdit} value={c.tier} onChange={(e) => patch({ tier: e.target.value })}>
                  <option value="">—</option><option value="A">A</option><option value="B">B</option><option value="C">C</option>
                </select>
              </label>
              <label>Stream
                <select className="field-input" disabled={!canEdit} value={c.stream} onChange={(e) => patch({ stream: e.target.value })}>
                  <option value="">—</option><option value="safety">Workplace Safety</option><option value="ops">Operations</option><option value="scl">Supply Chain</option>
                </select>
              </label>
              <label className="wide">Trigger (why now)
                <input className="field-input" disabled={!canEdit} defaultValue={c.trigger} maxLength={300}
                  onBlur={(e) => e.target.value !== c.trigger && patch({ trigger: e.target.value })} />
              </label>
            </div>
          </Section>
          <Section title="Details">
            <dl className="rec-dl">
              <dt>Phone</dt><dd>{c.phone || '—'}</dd>
              {c.domains.length > 0 && <><dt>Also</dt><dd>{c.domains.join(', ')}</dd></>}
              {c.revenue && <><dt>Revenue</dt><dd>{c.revenue}</dd></>}
              {c.founded_year && <><dt>Founded</dt><dd>{c.founded_year}</dd></>}
              {c.naics_codes.length > 0 && <><dt>NAICS</dt><dd>{c.naics_codes.join(', ')}</dd></>}
              {c.sic_codes.length > 0 && <><dt>SIC</dt><dd>{c.sic_codes.join(', ')}</dd></>}
              {li && <><dt>LinkedIn</dt><dd><a href={li} target="_blank" rel="noopener noreferrer">company page ↗</a></dd></>}
            </dl>
          </Section>
        </aside>
        <section className="rec-main" aria-label="Activity">
          <NoteComposer onSave={async (b) => { await api.addCompanyNote(id, b); await load(); onChanged() }} placeholder="A note about the company…" />
          <Timeline items={c.timeline} me={me} showWho onChanged={() => { load(); onChanged() }} />
        </section>
      </div>
    </div>
  )
}

// --- the host -------------------------------------------------------------------------
// `stack`: [{type: 'person'|'company', id}], newest last. Changes mark the list stale; it
// reloads once the panel closes.
export default function RecordPanel({ stack, setStack, me, meta, onClosed }) {
  const [users, setUsers] = useState(null)
  const [dirty, setDirty] = useState(false)
  useEffect(() => { if (isAdmin(me)) api.listUsers().then(setUsers).catch(() => setUsers([])) }, [me])
  const top = stack[stack.length - 1]
  const close = () => { setStack([]); onClosed?.(dirty); setDirty(false) }
  const back = () => setStack((s) => s.slice(0, -1))
  const push = (r) => setStack((s) => [...s, r])
  const changed = () => setDirty(true)
  return (
    <SlideOut open={!!top && !!meta} onClose={close} label={top?.type === 'company' ? 'Company' : 'Lead'}>
      {stack.length > 1 && <button className="linklike rec-back" onClick={back}>← Back</button>}
      {top?.type === 'person' && meta && (
        <PersonPanel key={`p${top.id}`} id={top.id} me={me} meta={meta} users={users} onChanged={changed}
          onOpenCompany={(cid) => push({ type: 'company', id: cid })}
          onDeleted={() => { setDirty(true); if (stack.length > 1) back(); else { setStack([]); onClosed?.(true) } }} />
      )}
      {top?.type === 'company' && meta && (
        <CompanyPanel key={`c${top.id}`} id={top.id} me={me} meta={meta} users={users} onChanged={changed}
          onOpenPerson={(pid) => push({ type: 'person', id: pid })} />
      )}
    </SlideOut>
  )
}
