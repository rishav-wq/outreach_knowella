import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'
import { stagger, tap } from './anim'

const rowVar = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { duration: 0.25 } } }

// Where leads come in and live. Apollo is the primary source (pulled directly by
// the campaign's ICP); CSV import stays for any hand-built or external list.
export default function Leads({ campaign, onNavigate }) {
  const [leads, setLeads] = useState(null)
  const [q, setQ] = useState('')
  const [limit, setLimit] = useState(25)
  const [msg, setMsg] = useState(null)   // { kind: 'ok'|'err', text }
  const [busy, setBusy] = useState('')   // '' | 'apollo' | 'csv'
  const [seeds, setSeeds] = useState([]) // lookalike seeds from the campaign config
  const [sel, setSel] = useState(() => new Set())  // selected lead keys for bulk actions
  const [confirm, setConfirm] = useState(null)      // 'exclude' | 'delete' | null
  const [working, setWorking] = useState(false)

  const load = () => api.getLeads(campaign).then(setLeads).catch(() => setLeads([]))
  useEffect(() => {
    setLeads(null); setMsg(null); setSel(new Set()); setConfirm(null); load()
    api.getCampaignConfig(campaign).then((cfg) => setSeeds((cfg.apollo || {}).lookalike_seeds || [])).catch(() => setSeeds([]))
  }, [campaign])

  // "More like this": seed Apollo's lookalike search with a proven lead, so the
  // next pull finds similar people (same kind of role at the same kind of company).
  const seedIds = new Set(seeds.map((s) => s.id))
  const toggleSeed = async (l) => {
    const on = !seedIds.has(l.apollo_id)
    try {
      const r = await api.setLookalike(campaign, l.key, on)
      setSeeds(r.lookalike_seeds || [])
      setMsg({ kind: 'ok', text: on
        ? `${l.name} added as a lookalike seed — the next Apollo pull also looks for people like them.`
        : `${l.name} removed from the lookalike seeds.` })
    } catch (e) {
      setMsg({ kind: 'err', text: `Could not update lookalike seeds: ${e.message || e}` })
    }
  }

  // multi-select for bulk actions on a pull
  const toggleSel = (key) => setSel((prev) => {
    const next = new Set(prev)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  })
  const clearSel = () => setSel(new Set())

  // Run a bulk action on the selected leads: 'exclude' keeps them in the library,
  // 'delete' wipes them everywhere. Both confirm first (delete is irreversible).
  const runBulk = async (kind) => {
    const keys = [...sel]
    setWorking(true); setMsg(null); setConfirm(null)
    try {
      if (kind === 'delete') {
        const r = await api.bulkDeleteLeads(campaign, keys)
        setMsg({ kind: 'ok', text: `Permanently deleted ${r.deleted} ${r.deleted === 1 ? 'lead' : 'leads'}.` })
      } else {
        const r = await api.bulkExcludeLeads(campaign, keys)
        setMsg({ kind: 'ok', text: `Removed ${r.excluded} ${r.excluded === 1 ? 'lead' : 'leads'} from this campaign — saved to the Library for future marketing.` })
      }
      clearSel()
      await load()
    } catch (e) {
      setMsg({ kind: 'err', text: `Bulk action failed: ${e.message || e}` })
    }
    setWorking(false)
  }

  const pullApollo = async () => {
    setBusy('apollo'); setMsg(null)
    try {
      const r = await api.pullApollo(campaign, limit)
      const credits = r.credits_used != null ? ` · used ${r.credits_used} Apollo ${r.credits_used === 1 ? 'credit' : 'credits'}` : ''
      setMsg(r.pulled
        ? { kind: 'ok', text: `Pulled ${r.pulled} ${r.pulled === 1 ? 'lead' : 'leads'} from Apollo${credits}. Run the pipeline on the Overview to research and draft them.` }
        : { kind: 'ok', text: 'Apollo returned no new leads for these filters — widen the titles, keywords, or geographies in the campaign settings.' })
      await load()
    } catch (e) {
      setMsg({ kind: 'err', text: `Apollo pull failed: ${e.message || e}` })
    }
    setBusy('')
  }

  const onUpload = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    setBusy('csv'); setMsg(null)
    try {
      const r = await api.pull(campaign, f, 'manual')
      setMsg({ kind: 'ok', text: `Imported ${r.pulled} ${r.pulled === 1 ? 'lead' : 'leads'} from ${f.name}. Run the pipeline on the Overview to research and draft them.` })
      await load()
    } catch {
      setMsg({ kind: 'err', text: 'Import failed — check the file is a CSV with name, company, and (ideally) email or domain columns.' })
    }
    setBusy('')
    e.target.value = ''
  }

  const sourceActions = (
    <div className="import-controls">
      <select className="src-select" value={limit} onChange={(e) => setLimit(Number(e.target.value))} title="How many leads to pull from Apollo" disabled={!!busy}>
        <option value={5}>5 leads</option>
        <option value={10}>10 leads</option>
        <option value={25}>25 leads</option>
        <option value={50}>50 leads</option>
        <option value={100}>100 leads</option>
        <option value={250}>250 leads</option>
        <option value={500}>500 leads</option>
      </select>
      <motion.button className="btn primary" {...tap} disabled={!!busy} onClick={pullApollo}>
        {busy === 'apollo' ? <><span className="spinner" /> Pulling…</> : <><Icon name="download" size={15} /> Pull from Apollo</>}
      </motion.button>
      <motion.label className={`btn ${busy === 'csv' ? 'is-busy' : ''}`} {...tap}>
        {busy === 'csv' ? <><span className="spinner spinner-dark" /> Importing…</> : <><Icon name="upload" size={15} /> Import CSV</>}
        <input type="file" accept=".csv" hidden disabled={!!busy} onChange={onUpload} />
      </motion.label>
    </div>
  )

  if (leads === null) {
    return (
      <div>
        <div className="import-bar">{sourceActions}</div>
        <div className="table-wrap">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div className="skel-row" key={i}>
              <Skeleton w={26} h={26} r={8} />
              <Skeleton w="18%" /><Skeleton w="14%" /><Skeleton w="18%" /><Skeleton w="22%" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (leads.length === 0) {
    return (
      <div>
        {msg && <div className={`banner ${msg.kind === 'err' ? 'error' : ''}`}>{msg.text}</div>}
        <motion.div className="empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <div className="empty-icon"><Icon name="download" size={24} /></div>
          <h3>Bring in your first leads</h3>
          <p className="muted">Pull directly from Apollo using this campaign&apos;s ICP — titles, industries, size, and geographies from the config. Or import a CSV for any other list. Missing domains and emails are enriched automatically.</p>
          <div className="empty-actions">{sourceActions}</div>
        </motion.div>
      </div>
    )
  }

  const filtered = leads.filter((l) => `${l.name} ${l.company} ${l.email}`.toLowerCase().includes(q.toLowerCase()))
  const allSelected = filtered.length > 0 && filtered.every((l) => sel.has(l.key))
  const toggleAll = () => setSel((prev) => {
    const next = new Set(prev)
    if (filtered.every((l) => prev.has(l.key))) filtered.forEach((l) => next.delete(l.key))
    else filtered.forEach((l) => next.add(l.key))
    return next
  })

  return (
    <div>
      <div className="import-bar">{sourceActions}</div>
      {msg && <div className={`banner ${msg.kind === 'err' ? 'error' : ''}`}>{msg.text}</div>}
      <div className="table-bar">
        <input className="search" type="search" placeholder="Search name, company, or email" value={q} onChange={(e) => setQ(e.target.value)} />
        {sel.size > 0 ? (
          <div className="bulk-bar">
            <span className="bulk-count">{sel.size} selected</span>
            <button className="btn" disabled={working} onClick={() => setConfirm('exclude')}>Remove from campaign</button>
            <button className="btn reject" disabled={working} onClick={() => setConfirm('delete')}><Icon name="x" size={14} /> Delete permanently</button>
            <button className="linklike" onClick={clearSel}>clear</button>
          </div>
        ) : (
          <span className="count">{filtered.length} of {leads.length} {leads.length === 1 ? 'lead' : 'leads'}</span>
        )}
      </div>
      {confirm && (
        <div className={`bulk-confirm ${confirm === 'delete' ? 'danger' : ''}`}>
          <div className="bulk-confirm-text">
            {confirm === 'delete'
              ? <>Permanently delete <b>{sel.size}</b> {sel.size === 1 ? 'lead' : 'leads'}? This removes them everywhere — <b>including the Library</b> — and can’t be undone. Use this only for junk you’ll never market to.</>
              : <>Remove <b>{sel.size}</b> {sel.size === 1 ? 'lead' : 'leads'} from <b>{campaign}</b>? Their drafts are cleared and they won’t be emailed here — but they’re saved to the Library for future marketing.</>}
          </div>
          <div className="bulk-confirm-actions">
            <button className="btn" onClick={() => setConfirm(null)}>Cancel</button>
            <button className={`btn ${confirm === 'delete' ? 'reject' : 'primary'}`} disabled={working} onClick={() => runBulk(confirm)}>
              {working ? <><span className="spinner spinner-dark" /> working…</> : (confirm === 'delete' ? 'Delete permanently' : 'Remove from campaign')}
            </button>
          </div>
        </div>
      )}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th className="chk-col"><input type="checkbox" checked={allSelected} onChange={toggleAll} title="Select all" /></th><th></th><th>Name</th><th>Title</th><th>Company</th><th>Email</th><th>Source</th><th>Status</th><th></th></tr>
          </thead>
          <motion.tbody variants={stagger} initial="hidden" animate="show">
            {filtered.map((l) => (
              <motion.tr key={l.key} variants={rowVar} className={sel.has(l.key) ? 'row-sel' : ''}>
                <td className="chk-col"><input type="checkbox" checked={sel.has(l.key)} onChange={() => toggleSel(l.key)} /></td>
                <td><div className="avatar sm">{(l.name || '?').slice(0, 1)}</div></td>
                <td>{l.name}</td>
                <td className="muted">{l.title || '—'}</td>
                <td>{l.company}</td>
                <td className="muted">{l.email || '—'}</td>
                <td>{l.source ? <span className="src-tag">{l.source}</span> : <span className="muted">—</span>}</td>
                <td><span className={`badge s-${l.status}`}>{l.status}</span></td>
                <td>{l.apollo_id && (
                  <button type="button" className={`seed-btn ${seedIds.has(l.apollo_id) ? 'on' : ''}`}
                    onClick={() => toggleSeed(l)}
                    title={seedIds.has(l.apollo_id)
                      ? 'Lookalike seed — the next Apollo pull also finds people like this lead. Click to remove.'
                      : 'More like this: seed the next Apollo pull with people similar to this lead.'}>
                    <Icon name="users" size={13} /> {seedIds.has(l.apollo_id) ? 'Seeded' : 'More like this'}
                  </button>
                )}</td>
              </motion.tr>
            ))}
          </motion.tbody>
        </table>
      </div>
    </div>
  )
}
