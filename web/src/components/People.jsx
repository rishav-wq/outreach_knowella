import { useEffect, useMemo, useState } from 'react'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'
import RecordPanel, { StageChip } from './RecordPanels'
import { avatarTint, initials } from './avatar'
import { useMe, isAdmin } from '../me'

const PAGE = 250   // rows rendered at once: thousands of rows made the tab crawl

// The Library: every lead, one row per person (whatever campaigns they're in), with
// their stage, owner and campaigns. Click a row for the full record. "No campaign"
// finds people who aren't in one; select some to add them to a campaign.
export default function People({ onPromoted }) {
  const me = useMe()
  const [data, setData] = useState(null)
  const [meta, setMeta] = useState(null)
  const [campaigns, setCampaigns] = useState([])
  const [users, setUsers] = useState([])
  const [err, setErr] = useState('')
  const [q, setQ] = useState('')
  const [fn, setFn] = useState('all')
  const [stage, setStage] = useState('all')
  const [camp, setCamp] = useState('all')
  const [owner, setOwner] = useState('all')
  const [eng, setEng] = useState('all')
  const [limit, setLimit] = useState(PAGE)
  const [sel, setSel] = useState(new Set())
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [stack, setStack] = useState([])
  const [adding, setAdding] = useState(false)
  const [copied, setCopied] = useState('')

  const load = () => api.listPeople().then((d) => { setData(d); setErr('') }).catch((e) => { setErr(api.errorText(e)); setData({ people: [], function_labels: {} }) })
  useEffect(() => {
    load()
    api.getCrmMeta().then(setMeta).catch(() => {})
    api.getCampaigns().then((cs) => { setCampaigns(cs); setTarget(cs[0] || '') }).catch(() => {})
    if (isAdmin(me)) api.listUsers().then(setUsers).catch(() => {})
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const people = data?.people || []
  const labels = data?.function_labels || {}
  const inCampaigns = useMemo(() => [...new Set(people.flatMap((p) => p.campaigns.map((c) => c.campaign)))].sort(), [people])
  const companiesN = useMemo(() => new Set(people.map((p) => p.company_id).filter(Boolean)).size, [people])
  const fnCounts = useMemo(() => {
    const c = {}
    for (const p of people) c[p.function] = (c[p.function] || 0) + 1
    return c
  }, [people])

  const shown = people.filter((p) => {
    if (fn !== 'all' && p.function !== fn) return false
    if (stage !== 'all' && p.stage !== stage) return false
    if (camp === 'none' && p.campaigns.length) return false
    if (camp !== 'all' && camp !== 'none' && !p.campaigns.some((c) => c.campaign === camp)) return false
    if (owner === 'mine' && p.owner !== me.id) return false
    if (owner === 'unowned' && p.owner) return false
    if (!['all', 'mine', 'unowned'].includes(owner) && p.owner !== owner) return false
    if (eng !== 'all' && p.engagement !== eng && !(eng === 'opened' && p.engagement === 'clicked')) return false
    if (q) {
      const hay = `${p.name} ${p.company} ${p.title} ${p.email} ${p.topics.join(' ')}`.toLowerCase()
      const needle = q.toLowerCase()
      if (!hay.includes(needle) && !hay.replace(/\s+/g, '').includes(needle.replace(/\s+/g, ''))) return false
    }
    return true
  })

  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleAll = () => setSel((s) => (s.size === shown.length ? new Set() : new Set(shown.map((p) => p.id))))
  const enroll = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await api.enrollPeople([...sel], target)
      const extra = [r.already ? `${r.already} already there` : '', r.suppressed ? `${r.suppressed} on do-not-contact, skipped` : ''].filter(Boolean)
      setMsg({ ok: true, text: `Added ${r.added} to ${target}${extra.length ? ` (${extra.join('; ')})` : ''}. Run its pipeline to draft them.` })
      setSel(new Set())
      load()
      onPromoted?.()
    } catch (e) { setMsg({ ok: false, text: `Couldn't add them: ${api.errorText(e)}` }) }
    setBusy(false)
  }
  const copyDomain = (p) => {
    const d = (p.email || '').split('@')[1]
    if (!d) return
    navigator.clipboard.writeText(d).then(() => { setCopied(p.id); setTimeout(() => setCopied(''), 1500) }).catch(() => {})
  }

  if (data === null) {
    return (
      <div>
        <div className="lib-head"><Skeleton w={220} h={30} /></div>
        <div className="table-wrap" style={{ marginTop: 18 }}>
          {[0, 1, 2, 3, 4].map((k) => <div className="skel-row" key={k}><Skeleton w={26} h={26} r={8} /><Skeleton w="18%" /><Skeleton w="16%" /><Skeleton w="14%" /><Skeleton w="20%" /></div>)}
        </div>
      </div>
    )
  }

  return (
    <div className="library">
      <div className="lib-head crm-head">
        <div>
          <div className="dash-eyebrow">Library</div>
          <div className="lib-title">{people.length.toLocaleString()} <small>leads at {companiesN.toLocaleString()} companies</small></div>
          <p className="dash-sub">One row per person, whatever campaigns they’re in. Click someone for their details, notes and history.</p>
        </div>
        <button className="btn primary" onClick={() => setAdding(true)}><Icon name="plus" size={14} /> Add lead</button>
      </div>
      {err && <div className="banner error">{err}</div>}

      <div className="lib-filters">
        <div className="lib-chips">
          {['all', 'safety', 'supply_chain', 'operations', 'other'].map((f) => (
            <button key={f} className={`chip ${fn === f ? 'on' : ''}`} onClick={() => setFn(f)}>
              {f === 'all' ? 'All roles' : (labels[f] || f)}
              <span className="chip-n">{f === 'all' ? people.length : (fnCounts[f] || 0)}</span>
            </button>
          ))}
        </div>
        <div className="lib-filters-right">
          <select className="src-select" aria-label="Stage" value={stage} onChange={(e) => setStage(e.target.value)}>
            <option value="all">Any stage</option>
            {(meta?.lead_stages || []).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className="src-select" aria-label="Campaign" value={camp} onChange={(e) => setCamp(e.target.value)}>
            <option value="all">All campaigns</option>
            <option value="none">No campaign</option>
            {inCampaigns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          {isAdmin(me) && (
            <select className="src-select" aria-label="Owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="all">Anyone’s</option>
              <option value="mine">Mine</option>
              <option value="unowned">Admins only (no owner)</option>
              {users.filter((u) => u.role !== 'marketing').map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
            </select>
          )}
          <select className="src-select" aria-label="Engagement" value={eng} onChange={(e) => setEng(e.target.value)}
            title="Who opened or clicked a marketing blast">
            <option value="all">Any engagement</option>
            <option value="opened">Opened a blast</option>
            <option value="clicked">Clicked a blast</option>
          </select>
          <input className="search" type="search" aria-label="Search" placeholder="Search name, company, title, topic" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      <div className="table-bar">
        <span className="count">{shown.length.toLocaleString()} of {people.length.toLocaleString()} shown</span>
        {sel.size > 0 && (
          <div className="lib-promote">
            <span>{sel.size} selected →</span>
            <select className="src-select" aria-label="Campaign to add them to" value={target} onChange={(e) => setTarget(e.target.value)}>
              {campaigns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <button className="btn primary" disabled={busy || !target} onClick={enroll}
              title="Add them to the campaign as fresh leads: its pipeline drafts them and you review as usual">
              {busy ? <><span className="spinner" /> Adding…</> : 'Add to campaign'}
            </button>
          </div>
        )}
      </div>
      {msg && <div className={`banner ${msg.ok ? '' : 'error'}`} style={{ marginTop: 10 }}>{msg.text}</div>}

      {shown.length === 0 ? (
        <div className="empty" style={{ marginTop: 20 }}>
          <p className="muted">{people.length === 0
            ? (isAdmin(me) ? 'No leads yet. Pull some into a campaign, or add one by hand.' : 'No leads of yours yet. Add one by hand, or ask an admin to give you a campaign.')
            : 'No leads match these filters.'}</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table crm-table">
            <thead>
              <tr>
                <th><input type="checkbox" aria-label="Select all shown" checked={sel.size > 0 && sel.size === shown.length} onChange={toggleAll} /></th>
                <th aria-label="Avatar" /><th>Name</th><th>Title</th><th>Company</th><th>Stage</th>
                {isAdmin(me) && <th>Owner</th>}<th>Campaigns</th><th>Email</th>
              </tr>
            </thead>
            <tbody>
              {shown.slice(0, limit).map((p) => (
                <tr key={p.id} className="crm-row" onClick={(e) => { if (!e.target.closest('button,input,a')) setStack([{ type: 'person', id: p.id }]) }}>
                  <td><input type="checkbox" aria-label={`Select ${p.name}`} checked={sel.has(p.id)} onChange={() => toggle(p.id)} /></td>
                  <td><div className="avatar sm" style={avatarTint(p.name)}>{initials(p.name)}</div></td>
                  <td>
                    <button className="linklike inline crm-name" onClick={() => setStack([{ type: 'person', id: p.id }])}>{p.name || p.email || '—'}</button>
                    {p.engagement && <span className={`badge ${p.engagement === 'clicked' ? 's-approved' : 's-drafted'}`} style={{ marginLeft: 7 }}
                      title={`${p.engagement} a marketing blast`}>{p.engagement}</span>}
                  </td>
                  <td className="muted">{p.title || '—'}</td>
                  <td>{p.company_id
                    ? <button className="linklike inline" onClick={() => setStack([{ type: 'company', id: p.company_id }])}>{p.company || '—'}</button>
                    : (p.company || '—')}</td>
                  <td><StageChip stage={p.stage} auto={p.stage_auto} /></td>
                  {isAdmin(me) && <td className="muted">{p.owner_name || 'Admins'}</td>}
                  <td className="muted crm-camps">{p.campaigns.length === 0 ? '—'
                    : `${p.campaigns.slice(0, 2).map((c) => c.campaign).join(', ')}${p.campaigns.length > 2 ? ` +${p.campaigns.length - 2}` : ''}`}</td>
                  <td className="muted">
                    {p.email ? (
                      <span className="lib-email">
                        {p.email}
                        <button className="icon-btn" onClick={() => copyDomain(p)}
                          title={copied === p.id ? 'Domain copied' : `Copy the domain (${p.email.split('@')[1]})`}>
                          <Icon name={copied === p.id ? 'check' : 'link'} size={12} />
                        </button>
                      </span>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length > limit && (
            <div className="lib-more">
              <button className="btn" onClick={() => setLimit(shown.length)}>Show all {shown.length.toLocaleString()} (first {limit} shown)</button>
            </div>
          )}
        </div>
      )}

      {adding && <AddLead onClose={() => setAdding(false)} onCreated={(id) => { setAdding(false); load(); setStack([{ type: 'person', id }]) }}
        onOpenExisting={(id) => { setAdding(false); setStack([{ type: 'person', id }]) }} />}
      <RecordPanel stack={stack} setStack={setStack} me={me} meta={meta} onClosed={(dirty) => { if (dirty) load() }} />
    </div>
  )
}

function AddLead({ onClose, onCreated, onOpenExisting }) {
  const [f, setF] = useState({ first_name: '', last_name: '', email: '', title: '', company: '', company_domain: '', phone: '', linkedin_url: '' })
  const [err, setErr] = useState(null)   // {text, id}
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const save = async (e) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      const r = await api.createPerson(f)
      onCreated(r.id)
    } catch (ex) {
      let id = ''
      try { id = JSON.parse(ex.message).detail?.id || '' } catch { /* not JSON */ }
      setErr({ text: api.errorText(ex), id })
    }
    setBusy(false)
  }
  const field = (k, label, props = {}) => (
    <label className="field"><span>{label}</span><input className="field-input" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} {...props} /></label>
  )
  return (
    <div className="modal-scrim" onClick={onClose}>
      <form className="rec-modal" role="dialog" aria-modal="true" aria-label="Add a lead" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h2>Add a lead</h2>
        <p className="muted">They’re yours once added. An email or a LinkedIn link is needed, so the same person is never added twice.</p>
        <div className="rec-form two">
          {field('first_name', 'First name', { autoFocus: true })}
          {field('last_name', 'Last name')}
          {field('email', 'Email', { type: 'email' })}
          {field('phone', 'Phone')}
          {field('title', 'Title')}
          {field('company', 'Company')}
          {field('company_domain', 'Company website', { placeholder: 'acme.com' })}
          {field('linkedin_url', 'LinkedIn', { placeholder: 'linkedin.com/in/…' })}
        </div>
        {err && (
          <div className="banner error" style={{ marginTop: 12 }}>
            {err.text}{err.id && <button type="button" className="linklike inline" style={{ marginLeft: 8 }} onClick={() => onOpenExisting(err.id)}>Open them</button>}
          </div>
        )}
        <div className="rec-form-row">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={busy}>{busy ? 'Adding…' : 'Add lead'}</button>
        </div>
      </form>
    </div>
  )
}
