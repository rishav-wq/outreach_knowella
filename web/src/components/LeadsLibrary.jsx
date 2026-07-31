import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'
import { stagger } from './anim'
import { avatarTint, initials } from './avatar'

const rowVar = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { duration: 0.25 } } }

// The master leads library: every lead we've EVER pulled, across all campaigns —
// kept forever (excluding a lead from a campaign never deletes it, just marks it
// "not a fit"), grouped by persona bucket (from title) and topic (from the campaign
// it came in on) so the whole pool is reusable for future marketing. The per-campaign
// Leads tab shows one campaign's working set; this shows everything.
export default function LeadsLibrary({ onPromoted }) {
  const [data, setData] = useState(null)   // { leads, function_labels }
  const [q, setQ] = useState('')
  const [fn, setFn] = useState('all')      // function bucket filter
  const [camp, setCamp] = useState('all')  // campaign filter
  const [eng, setEng] = useState('all')    // engagement filter: all | opened | clicked
  const [sel, setSel] = useState(new Set())            // selected lead keys (promote)
  const [campaigns2, setCampaigns2] = useState([])     // promotable campaigns
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [copied, setCopied] = useState('')   // lead key whose domain was just copied

  const copyDomain = (l) => {
    const domain = (l.email || '').split('@')[1]
    if (!domain) return
    navigator.clipboard.writeText(domain).then(() => {
      setCopied(l.key)
      setTimeout(() => setCopied(''), 1500)
    }).catch(() => {})
  }

  useEffect(() => {
    api.getAllLeads().then(setData).catch(() => setData({ leads: [], function_labels: {} }))
    api.getCampaigns().then((cs) => { setCampaigns2(cs); setTarget(cs[0] || '') }).catch(() => {})
  }, [])

  const leads = data?.leads || []
  const labels = data?.function_labels || {}
  const campaigns = useMemo(() => [...new Set(leads.map((l) => l.campaign).filter(Boolean))].sort(), [leads])
  const fnCounts = useMemo(() => {
    const c = {}
    for (const l of leads) c[l.function] = (c[l.function] || 0) + 1
    return c
  }, [leads])

  const shown = leads.filter((l) => {
    if (fn !== 'all' && l.function !== fn) return false
    if (camp !== 'all' && l.campaign !== camp) return false
    if (eng !== 'all' && l.engagement !== eng && !(eng === 'opened' && l.engagement === 'clicked')) return false
    if (q) {
      const hay = `${l.name} ${l.company} ${l.title} ${l.email} ${(l.topics || []).join(' ')}`.toLowerCase()
      if (!hay.includes(q.toLowerCase())) return false
    }
    return true
  })

  const toggle = (key) => setSel((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n })
  const toggleAll = () => setSel((s) => s.size === shown.length ? new Set() : new Set(shown.map((l) => l.key)))
  const promote = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await api.promoteLeads([...sel], target)
      setMsg(`Added ${r.added} to ${target}${r.suppressed ? ` (${r.suppressed} suppressed skipped)` : ''} — run its pipeline to draft them.`)
      setSel(new Set())
      onPromoted?.()
    } catch (e) { setMsg(`Could not promote: ${String(e.message).slice(0, 180)}`) }
    finally { setBusy(false) }
  }

  const fnChips = ['all', 'safety', 'supply_chain', 'operations', 'other']

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
      <div className="lib-head">
        <div>
          <div className="dash-eyebrow">Leads library</div>
          <div className="lib-title">{leads.length.toLocaleString()} <small>leads across {campaigns.length} {campaigns.length === 1 ? 'campaign' : 'campaigns'}</small></div>
          <p className="dash-sub">Every lead you’ve ever pulled, across all campaigns — grouped by role and topic so the whole pool is reusable for future marketing. Removing a lead from a campaign marks it “not a fit” but never drops it from here.</p>
        </div>
      </div>

      <div className="lib-filters">
        <div className="lib-chips">
          {fnChips.map((f) => (
            <button key={f} className={`chip ${fn === f ? 'on' : ''}`} onClick={() => setFn(f)}>
              {f === 'all' ? 'All roles' : (labels[f] || f)}
              <span className="chip-n">{f === 'all' ? leads.length : (fnCounts[f] || 0)}</span>
            </button>
          ))}
        </div>
        <div className="lib-filters-right">
          <select className="src-select" value={eng} onChange={(e) => setEng(e.target.value)}
            title="Marketing engagement — who opened/clicked a blast (the warm slice)">
            <option value="all">Any engagement</option>
            <option value="opened">Opened a blast</option>
            <option value="clicked">Clicked a blast</option>
          </select>
          {campaigns.length > 1 && (
            <select className="src-select" value={camp} onChange={(e) => setCamp(e.target.value)} title="Filter by the campaign a lead came in on">
              <option value="all">All campaigns</option>
              {campaigns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
          <input className="search" type="search" placeholder="Search name, company, title, topic" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      <div className="table-bar">
        <span className="count">{shown.length} of {leads.length} shown</span>
        {sel.size > 0 && (
          <div className="lib-promote">
            <span>{sel.size} selected →</span>
            <select className="src-select" value={target} onChange={(e) => setTarget(e.target.value)}>
              {campaigns2.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <button className="btn primary" disabled={busy || !target} onClick={promote}
              title="Copy into the campaign as fresh leads — its pipeline drafts them, you review as usual">
              {busy ? <><span className="spinner" /> Adding…</> : 'Add to campaign'}
            </button>
          </div>
        )}
      </div>
      {msg && <div className="banner" style={{ marginTop: 10 }}>{msg}</div>}

      {shown.length === 0 ? (
        <div className="empty" style={{ marginTop: 20 }}>
          <p className="muted">{leads.length === 0 ? 'No leads yet — pull some from a campaign and they’ll collect here.' : 'No leads match these filters.'}</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th><input type="checkbox" checked={sel.size > 0 && sel.size === shown.length} onChange={toggleAll} /></th>
                <th></th><th>Name</th><th>Title</th><th>Company</th><th>Email</th><th>Role</th><th>Topics</th><th>Campaign</th><th>Status</th>
              </tr>
            </thead>
            <motion.tbody variants={stagger} initial="hidden" animate="show">
              {shown.map((l) => (
                <motion.tr key={l.key} variants={rowVar}>
                  <td><input type="checkbox" checked={sel.has(l.key)} onChange={() => toggle(l.key)} /></td>
                  <td><div className="avatar sm" style={avatarTint(l.name)}>{initials(l.name)}</div></td>
                  <td>
                    {l.name || '—'}
                    {l.engagement && <span className={`badge ${l.engagement === 'clicked' ? 's-approved' : 's-drafted'}`}
                      style={{ marginLeft: 7 }} title={`${l.engagement} a marketing blast — warm`}>{l.engagement}</span>}
                  </td>
                  <td className="muted">{l.title || '—'}</td>
                  <td>{l.company || '—'}</td>
                  <td className="muted">
                    {l.email ? (
                      <span className="lib-email">
                        {l.email}
                        <button className="icon-btn" onClick={() => copyDomain(l)}
                          title={copied === l.key ? 'Domain copied!' : `Copy domain (${l.email.split('@')[1]}) — paste into Settings → Do not contact to block the whole company`}>
                          <Icon name={copied === l.key ? 'check' : 'link'} size={12} />
                        </button>
                      </span>
                    ) : '—'}
                  </td>
                  <td><span className={`fn-tag fn-${l.function}`}>{labels[l.function] || l.function}</span></td>
                  <td>
                    <div className="lib-topics">
                      {(l.topics || []).slice(0, 3).map((t) => <span key={t} className="topic-tag">{t}</span>)}
                      {(l.topics || []).length === 0 && <span className="muted">—</span>}
                    </div>
                  </td>
                  <td className="muted">{l.campaign || '—'}</td>
                  <td>{l.status === 'excluded' ? <span className="badge s-dropped">not a fit</span> : <span className={`badge s-${l.status}`}>{l.status}</span>}</td>
                </motion.tr>
              ))}
            </motion.tbody>
          </table>
        </div>
      )}
    </div>
  )
}
