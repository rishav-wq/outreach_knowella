import { useEffect, useMemo, useState } from 'react'
import * as api from '../api'
import Skeleton from './Skeleton'
import RecordPanel, { StageChip } from './RecordPanels'
import { avatarTint, initials } from './avatar'
import { useMe, isAdmin } from '../me'

const PAGE = 250

// Every company your leads work at: its stage (worked out from its people until someone
// sets it), how many of its people have been reached, and its owner. The strip counts
// companies per stage; click one to filter.
export default function Companies() {
  const me = useMe()
  const [data, setData] = useState(null)
  const [meta, setMeta] = useState(null)
  const [users, setUsers] = useState([])
  const [err, setErr] = useState('')
  const [q, setQ] = useState('')
  const [stage, setStage] = useState('all')
  const [owner, setOwner] = useState('all')
  const [limit, setLimit] = useState(PAGE)
  const [stack, setStack] = useState([])

  const load = () => api.listCompanies().then((d) => { setData(d); setErr('') }).catch((e) => { setErr(api.errorText(e)); setData({ companies: [] }) })
  useEffect(() => {
    load()
    api.getCrmMeta().then(setMeta).catch(() => {})
    if (isAdmin(me)) api.listUsers().then(setUsers).catch(() => {})
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const companies = data?.companies || []
  const counts = useMemo(() => {
    const c = {}
    for (const x of companies) c[x.stage] = (c[x.stage] || 0) + 1
    return c
  }, [companies])
  const shown = companies
    .filter((x) => {
      if (stage !== 'all' && x.stage !== stage) return false
      if (owner === 'mine' && x.owner !== me.id) return false
      if (owner === 'unowned' && x.owner) return false
      if (!['all', 'mine', 'unowned'].includes(owner) && x.owner !== owner) return false
      if (q) {
        const hay = `${x.name} ${x.domain} ${x.industry} ${x.location}`.toLowerCase()
        if (!hay.includes(q.toLowerCase())) return false
      }
      return true
    })
    .sort((a, b) => b.engaged - a.engaged || b.contacted - a.contacted || a.name.localeCompare(b.name))

  if (data === null) {
    return <div><Skeleton w={220} h={30} /><Skeleton h={80} r={12} style={{ marginTop: 18 }} /><Skeleton h={300} r={12} style={{ marginTop: 14 }} /></div>
  }
  const open = meta?.company_open || []
  const closed = (meta?.company_stages || []).filter((s) => !open.includes(s))
  const max = Math.max(1, ...open.map((s) => counts[s] || 0))
  return (
    <div className="library">
      <div className="lib-head crm-head">
        <div>
          <div className="dash-eyebrow">Companies</div>
          <div className="lib-title">{companies.length.toLocaleString()} <small>companies</small></div>
          <p className="dash-sub">Each company your leads work at. A company’s stage follows its people until someone sets it.</p>
        </div>
      </div>
      {err && <div className="banner error">{err}</div>}

      <section className="crm-strip" aria-label="Companies by stage">
        {open.map((s) => (
          <button key={s} className={`crm-strip-cell ${stage === s ? 'on' : ''}`} aria-pressed={stage === s}
            onClick={() => setStage(stage === s ? 'all' : s)}>
            <span className="crm-strip-name">{s}</span>
            <b>{(counts[s] || 0).toLocaleString()}</b>
            <span className="crm-strip-bar"><i style={{ width: `${Math.max(3, Math.round(((counts[s] || 0) / max) * 100))}%` }} /></span>
          </button>
        ))}
        <div className="crm-strip-closed">
          {closed.map((s) => (
            <button key={s} className={`chip ${stage === s ? 'on' : ''}`} aria-pressed={stage === s} onClick={() => setStage(stage === s ? 'all' : s)}>
              {s} <span className="chip-n">{counts[s] || 0}</span>
            </button>
          ))}
        </div>
      </section>

      <div className="lib-filters">
        <div className="lib-filters-right" style={{ marginLeft: 0 }}>
          {isAdmin(me) && (
            <select className="src-select" aria-label="Owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="all">Anyone’s</option>
              <option value="mine">Mine</option>
              <option value="unowned">Admins only (no owner)</option>
              {users.filter((u) => u.role !== 'marketing').map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
            </select>
          )}
          <input className="search" type="search" aria-label="Search" placeholder="Search name, domain, industry, place" value={q} onChange={(e) => setQ(e.target.value)} />
          {stage !== 'all' && <button className="linklike inline" onClick={() => setStage('all')}>Clear stage: {stage}</button>}
        </div>
      </div>

      <div className="table-bar"><span className="count">{shown.length.toLocaleString()} of {companies.length.toLocaleString()} shown</span></div>
      {shown.length === 0 ? (
        <div className="empty" style={{ marginTop: 20 }}><p className="muted">{companies.length ? 'No companies match these filters.' : 'No companies yet: they appear with your leads.'}</p></div>
      ) : (
        <div className="table-wrap">
          <table className="table crm-table">
            <thead>
              <tr><th aria-label="Logo" /><th>Company</th><th>Industry</th><th>Size</th><th>Location</th><th>Stage</th><th>Reached</th>{isAdmin(me) && <th>Owner</th>}</tr>
            </thead>
            <tbody>
              {shown.slice(0, limit).map((x) => (
                <tr key={x.id} className="crm-row" onClick={(e) => { if (!e.target.closest('button,a')) setStack([{ type: 'company', id: x.id }]) }}>
                  <td><div className="avatar sm sq" style={avatarTint(x.name)}>{initials(x.name)}</div></td>
                  <td>
                    <button className="linklike inline crm-name" onClick={() => setStack([{ type: 'company', id: x.id }])}>{x.name || x.domain}</button>
                    <div className="muted crm-domain">{x.domain}</div>
                  </td>
                  <td className="muted">{x.industry || '—'}</td>
                  <td className="muted">{x.employees ? x.employees.toLocaleString() : '—'}</td>
                  <td className="muted">{x.location || '—'}</td>
                  <td><StageChip stage={x.stage} auto={x.stage_auto} /></td>
                  <td className="muted" title="Leads who replied or booked a meeting / leads emailed / leads here">
                    {x.engaged > 0 && <b className="crm-engaged">{x.engaged} engaged · </b>}{x.contacted} of {x.people}
                  </td>
                  {isAdmin(me) && <td className="muted">{x.owner_name || 'Admins'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length > limit && (
            <div className="lib-more"><button className="btn" onClick={() => setLimit(shown.length)}>Show all {shown.length.toLocaleString()} (first {limit} shown)</button></div>
          )}
        </div>
      )}
      <RecordPanel stack={stack} setStack={setStack} me={me} meta={meta} onClosed={(dirty) => { if (dirty) load() }} />
    </div>
  )
}
