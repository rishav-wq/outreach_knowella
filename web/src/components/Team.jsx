import { Fragment, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Skeleton from './Skeleton'
import { useMe } from '../me'

// The admin's page: everyone's training ramp (with the manager sign-offs), who has
// which role, who owns which campaign, and the playbook file itself. Every rule here
// is enforced by the server; this page only makes it easy to see and change.

const ROLES = [['sales', 'Sales'], ['marketing', 'Marketing'], ['admin', 'Admin']]
const LOG_COLS = [['dials', 'Dials'], ['convos', 'Conversations'], ['emails', 'Emails'],
  ['li', 'LinkedIn'], ['accts', 'Accounts'], ['mtgs', 'Meetings']]
const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '')
const ago = (iso) => {
  if (!iso) return 'never'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}
const short = (t, n = 5) => {
  const w = String(t || '').split(/\s+/)
  return w.length > n ? `${w.slice(0, n).join(' ')}…` : t
}
const card = { initial: { opacity: 0, y: 10 }, animate: { opacity: 1, y: 0 } }

// --- training ramp ---------------------------------------------------------------
function Ramp({ data, onSignoff }) {
  const [open, setOpen] = useState('')
  const [events, setEvents] = useState({})
  const [err, setErr] = useState('')
  if (!data) return <Skeleton h={160} r={10} />
  const { people, modules_total: total, signoff_ids: signoffs = [], tracks = [] } = data
  const labels = data.signoff_labels || {}
  if (!total) {
    return <div className="muted" style={{ fontSize: 13 }}>Upload the playbook (below) and everyone’s progress shows here.</div>
  }
  // The people being trained: sales, plus anyone else who has started.
  const rows = people
    .filter((p) => p.active && (p.role === 'sales' || p.modules_done > 0 || Object.keys(p.quiz_best || {}).length))
    .sort((a, b) => (a.role === 'sales' ? 0 : 1) - (b.role === 'sales' ? 0 : 1) || b.modules_done - a.modules_done)
  if (!rows.length) {
    return <div className="muted" style={{ fontSize: 13 }}>Nobody in sales has signed in yet. People appear here after their first sign-in.</div>
  }
  const toggle = async (p) => {
    if (open === p.id) { setOpen(''); return }
    setOpen(p.id)
    if (!events[p.id]) {
      try { const ev = await api.getTrainingEvents(p.id); setEvents((e) => ({ ...e, [p.id]: ev })) }
      catch (e) { setEvents((x) => ({ ...x, [p.id]: [] })); setErr(api.errorText(e)) }
    }
  }
  const sign = async (p, item, value) => {
    setErr('')
    try { await onSignoff(p.id, item, value) } catch (e) { setErr(api.errorText(e)) }
  }
  const evText = (e) => {
    const t = data.module_titles?.[e.ref] || e.ref
    const tr = tracks.find((x) => x.id === e.ref)?.name || e.ref
    const c = data.cert_labels?.[e.ref] || labels[e.ref] || e.ref
    if (e.type === 'module_done') return <>Completed <b>{t}</b></>
    if (e.type === 'module_undone') return <>Unmarked <b>{t}</b></>
    if (e.type === 'quiz_attempt') return <><b>{tr}</b> quiz: {e.score ?? '?'}%</>
    if (e.type === 'cert') return <>Checklist: {short(c, 9)} {e.value ? 'ticked' : 'unticked'}</>
    if (e.type === 'signoff') return <>{e.value ? 'Signed off' : 'Sign-off removed'}: {short(labels[e.ref] || c, 9)} <span className="muted">by {e.by}</span></>
    return e.type
  }
  return (
    <>
      {err && <div className="banner error">{err}</div>}
      <div className="table-wrap">
        <table className="table team-ramp">
          <thead>
            <tr>
              <th>Person</th><th>Modules</th><th>Quizzes</th>
              <th title="Ticked by a manager here; the person can't tick these themselves">Manager sign-offs</th>
              <th>Last active</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const pct = total ? Math.round((p.modules_done / total) * 100) : 0
              const last = [p.last_saved, p.last_seen].filter(Boolean).sort().pop()
              return (
                <Fragment key={p.id}>
                  <tr>
                    <td>
                      <div className="team-name">{p.name || p.email.split('@')[0]}</div>
                      <div className="muted team-email">{p.email}</div>
                    </td>
                    <td>
                      <div className="team-bar" title={`${pct}%`}><i style={{ width: `${pct}%` }} /></div>
                      <span className="team-num">{p.modules_done} / {total}</span>
                    </td>
                    <td>
                      <div className="team-quiz">
                        {tracks.map((t) => {
                          const s = p.quiz_best?.[t.id]
                          return (
                            <span key={t.id} className={`team-q ${s == null ? '' : s >= 80 ? 'pass' : 'low'}`}
                              title={`${t.name}: ${s == null ? 'not taken' : `best ${s}%`}${p.quiz_attempts?.[t.id] ? `, ${p.quiz_attempts[t.id]} attempt${p.quiz_attempts[t.id] === 1 ? '' : 's'}` : ''}`}>
                              {t.name.split(/[\s&]/)[0]} {s == null ? '–' : `${s}%`}
                            </span>
                          )
                        })}
                      </div>
                    </td>
                    <td>
                      <div className="team-sign">
                        {signoffs.map((id) => (
                          <label key={id} title={labels[id] || id}>
                            <input type="checkbox" checked={!!p.cert?.[id]} onChange={(e) => sign(p, id, e.target.checked)} />
                            <span>{short(labels[id] || id, 3)}</span>
                          </label>
                        ))}
                      </div>
                    </td>
                    <td className="muted">{ago(last)}</td>
                    <td><button className="linklike" onClick={() => toggle(p)}>{open === p.id ? 'Hide' : 'Details'}</button></td>
                  </tr>
                  {open === p.id && (
                    <tr className="team-detail">
                      <td colSpan={6}>
                        <div className="team-detail-grid">
                          <div>
                            <div className="drawer-label">Timeline</div>
                            {!events[p.id] ? <Skeleton h={60} /> : events[p.id].length === 0
                              ? <div className="muted" style={{ fontSize: 12.5 }}>Nothing yet.</div>
                              : (
                                <ul className="team-events">
                                  {events[p.id].slice(0, 40).map((e, i) => (
                                    <li key={i}><span className="muted">{day(e.at)}</span> {evText(e)}</li>
                                  ))}
                                </ul>
                              )}
                          </div>
                          <div>
                            <div className="drawer-label">Activity log (last 14 days, as they entered it)</div>
                            {Object.keys(p.log || {}).length === 0
                              ? <div className="muted" style={{ fontSize: 12.5 }}>No days logged.</div>
                              : (
                                <table className="team-log">
                                  <thead><tr><th>Day</th>{LOG_COLS.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
                                  <tbody>
                                    {Object.keys(p.log).sort().reverse().map((d) => (
                                      <tr key={d}><td>{d}</td>{LOG_COLS.map(([k]) => <td key={k}>{+p.log[d]?.[k] || 0}</td>)}</tr>
                                    ))}
                                  </tbody>
                                </table>
                              )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

// --- people and roles -------------------------------------------------------------
function People({ users, onUpdate }) {
  const me = useMe()
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  if (!users) return <Skeleton h={120} r={10} />
  const change = async (u, patch) => {
    setErr(''); setBusy(u.id)
    try { await onUpdate(u.id, patch) } catch (e) { setErr(api.errorText(e)) }
    setBusy('')
  }
  return (
    <>
      {err && <div className="banner error">{err}</div>}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Person</th><th>Role</th><th>Access</th>
            <th title="Their first day: the Today page's targets ramp from it. Empty means their first sign-in.">Started</th>
            <th>Last seen</th></tr></thead>
          <tbody>
            {users.map((u) => {
              const self = u.id === me.id
              return (
                <tr key={u.id} className={u.active ? '' : 'team-off'}>
                  <td>
                    <div className="team-name">{u.name || u.email.split('@')[0]}{self && <span className="muted"> (you)</span>}</div>
                    <div className="muted team-email">{u.email}</div>
                  </td>
                  <td>
                    <select className="field-input team-select" value={u.role} disabled={u.pinned_admin || busy === u.id}
                      title={u.pinned_admin ? 'Set on the server (ADMIN_EMAILS), so it can’t be changed here' : ''}
                      onChange={(e) => change(u, { role: e.target.value })}>
                      {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </td>
                  <td>
                    {u.pinned_admin || self
                      ? <span className="muted" style={{ fontSize: 12.5 }}>{u.active ? 'On' : 'Off'}</span>
                      : (
                        <button className={`btn ${u.active ? '' : 'primary'}`} disabled={busy === u.id}
                          onClick={() => change(u, { active: !u.active })}>
                          {u.active ? 'Switch off' : 'Switch on'}
                        </button>
                      )}
                  </td>
                  <td>
                    <input type="date" className="field-input team-date" aria-label={`${u.name || u.email} started on`}
                      value={u.start_date || (u.created_at || '').slice(0, 10)} disabled={busy === u.id}
                      onChange={(e) => change(u, { start_date: e.target.value })} />
                  </td>
                  <td className="muted">{ago(u.last_seen)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

// --- campaign owners --------------------------------------------------------------
function Owners({ owners, users, onSet }) {
  const [err, setErr] = useState('')
  if (!owners || !users) return <Skeleton h={100} r={10} />
  if (!owners.length) return <div className="muted" style={{ fontSize: 13 }}>No campaigns yet.</div>
  const eligible = users.filter((u) => u.active && (u.role === 'sales' || u.role === 'admin'))
  const set = async (campaign, owner) => {
    setErr('')
    try { await onSet(campaign, owner) } catch (e) { setErr(api.errorText(e)) }
  }
  return (
    <>
      {err && <div className="banner error">{err}</div>}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Campaign</th><th>Owner</th></tr></thead>
          <tbody>
            {owners.map((o) => {
              const known = !o.owner || eligible.some((u) => u.id === o.owner)
              return (
                <tr key={o.campaign}>
                  <td><code>{o.campaign}</code></td>
                  <td>
                    <select className="field-input team-select" value={o.owner} onChange={(e) => set(o.campaign, e.target.value)}>
                      <option value="">Admins only</option>
                      {!known && <option value={o.owner}>{o.owner_email || o.owner} (switched off)</option>}
                      {eligible.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
                    </select>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

// --- the playbook file ------------------------------------------------------------
function Playbook({ versions, onUploaded }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)   // { ok, text }
  const cur = versions?.[0]
  const upload = async (e) => {
    const f = e.target.files[0]
    e.target.value = ''
    if (!f) return
    setBusy(true); setMsg(null)
    try {
      const r = await api.uploadPlaybook(f)
      const miss = r.swaps_missing?.length
        ? ` ${r.swaps_missing.length} of the app’s small text edits didn’t match this version (${r.swaps_missing.join(', ')}); the page still works.`
        : ''
      setMsg({ ok: true, text: `Uploaded: ${r.modules} modules${r.has_board ? ', with the Target board' : ''}. Everyone gets it the next time they open Training, and their progress carries over.${miss}` })
      onUploaded()
    } catch (err) {
      setMsg({ ok: false, text: `Not uploaded: ${api.errorText(err)}` })
    }
    setBusy(false)
  }
  return (
    <>
      {versions === null ? <Skeleton w="50%" h={14} /> : cur ? (
        <div className="team-pb">
          <b>{cur.filename || 'Playbook'}</b>
          <span className="muted"> · {cur.modules} modules{cur.has_board ? ' · Target board' : ''} · uploaded {day(cur.uploaded_at)} by {cur.uploaded_by || 'an admin'}</span>
          {cur.swaps_missing?.length > 0 && (
            <div className="pub-warn">Edits that didn’t apply to this version: {cur.swaps_missing.join(', ')}.</div>
          )}
        </div>
      ) : <div className="muted" style={{ fontSize: 13 }}>No playbook uploaded yet.</div>}
      <div className="ready-form" style={{ marginTop: 12 }}>
        <label className={`btn primary ${busy ? 'is-busy' : ''}`}>
          {busy ? <><span className="spinner" /> Uploading…</> : (cur ? 'Upload a new version' : 'Upload the playbook')}
          <input type="file" accept=".html,text/html" hidden disabled={busy} onChange={upload} />
        </label>
        <span className="muted" style={{ fontSize: 12 }}>The HTML file. It’s kept in the app’s database, never in the code repository.</span>
      </div>
      {msg && <div className={`banner ${msg.ok ? '' : 'error'}`} style={{ marginTop: 12, marginBottom: 0 }}>{msg.text}</div>}
      {versions?.length > 1 && (
        <details className="team-versions">
          <summary>Earlier versions ({versions.length - 1})</summary>
          <ul className="supp-list">
            {versions.slice(1).map((v) => (
              <li key={v.id}><span>{v.filename || v.id}</span><span className="muted"> · {v.modules} modules · {day(v.uploaded_at)} by {v.uploaded_by}</span></li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

export default function Team() {
  const [ramp, setRamp] = useState(null)
  const [users, setUsers] = useState(null)
  const [owners, setOwners] = useState(null)
  const [versions, setVersions] = useState(null)
  const [error, setError] = useState('')

  const loadRamp = () => api.getTrainingTeam().then(setRamp).catch((e) => setError(api.errorText(e)))
  const loadVersions = () => api.listPlaybookVersions().then(setVersions).catch(() => setVersions([]))
  useEffect(() => {
    loadRamp(); loadVersions()
    api.listUsers().then(setUsers).catch((e) => setError(api.errorText(e)))
    api.getCampaignOwners().then(setOwners).catch(() => setOwners([]))
  }, [])

  const updateUser = async (id, patch) => {
    const u = await api.updateUser(id, patch)
    setUsers((us) => us.map((x) => (x.id === id ? u : x)))
    loadRamp()
  }
  const setOwner = async (campaign, owner) => {
    const r = await api.setCampaignOwner(campaign, owner)
    setOwners((os) => os.map((o) => (o.campaign === campaign
      ? { ...o, owner: r.owner, owner_email: r.owner_email } : o)))
  }
  // The box ticks at once; if the server refuses, it goes back and the error shows.
  const signoff = async (user, item, value) => {
    const mark = (v) => setRamp((d) => ({
      ...d,
      people: d.people.map((p) => (p.id === user ? { ...p, cert: { ...(p.cert || {}), [item]: v } } : p)),
    }))
    mark(value)
    try { await api.setSignoff(user, item, value) } catch (e) { mark(!value); throw e }
  }

  return (
    <div className="settings team">
      {error && <div className="banner error">{error}</div>}
      <motion.section className="set-card" {...card}>
        <div className="drawer-label">Training ramp</div>
        <div className="muted team-lede">
          Progress each person has saved in the playbook. Tick a sign-off once you’ve checked the work: they can’t tick
          those themselves, and they see it the next time they open Training.
        </div>
        <Ramp data={ramp} onSignoff={signoff} />
      </motion.section>

      <motion.section className="set-card" {...card}>
        <div className="drawer-label">People and roles</div>
        <div className="muted team-lede">
          People appear here the first time they sign in, as Sales. Sales sees only their own campaigns; Marketing sees
          blasts, publications and audiences; Admins see everything. Switching someone off ends their access at once.
        </div>
        <People users={users} onUpdate={updateUser} />
      </motion.section>

      <motion.section className="set-card" {...card}>
        <div className="drawer-label">Who owns which campaign</div>
        <div className="muted team-lede">
          The owner works the campaign (its leads, drafts and replies); other sales people don’t see it. Campaigns
          someone creates are theirs automatically.
        </div>
        <Owners owners={owners} users={users} onSet={setOwner} />
      </motion.section>

      <motion.section className="set-card" {...card}>
        <div className="drawer-label">Playbook</div>
        <Playbook versions={versions} onUploaded={() => { loadVersions(); loadRamp() }} />
      </motion.section>
    </div>
  )
}
