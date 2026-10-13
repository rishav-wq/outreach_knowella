import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Skeleton from './Skeleton'
import RecordPanel from './RecordPanels'
import { TaskForm, TaskRow } from './Work'
import { useMe, isAdmin } from '../me'

// A rep's day (Sid's items 30 and 31): what's overdue and due, what they've done today,
// and the playbook's targets for where they are on the ramp. Admins also see the team,
// and can open anyone's day.

const TILES = [
  ['dials', 'Dials'], ['convos', 'Conversations'], ['emails', 'Emails'],
  ['li', 'LinkedIn touches'], ['accts', 'New accounts'], ['mtgs', 'Meetings booked'],
]
const num = (v) => (Number.isInteger(v) ? v : Number(v || 0).toFixed(1))

function Tiles({ activity, ramp }) {
  return (
    <div className="act-grid">
      {TILES.map(([k, label]) => {
        const v = activity[k] || 0
        const t = ramp.has_targets ? ramp.targets[k] : null
        const pct = t ? Math.min(100, Math.round((v / t) * 100)) : 0
        return (
          <div key={k} className={`act-tile ${t && v >= t ? 'met' : ''}`}>
            <div className="act-label">{label}</div>
            <div className="act-num">{num(v)}{t ? <span className="act-of"> / {num(t)}</span> : null}</div>
            {t ? <div className="act-bar" aria-hidden="true"><span style={{ width: `${pct}%` }} /></div>
              : <div className="act-bar off" aria-hidden="true" />}
          </div>
        )
      })}
    </div>
  )
}

function TaskGroup({ title, tasks, empty, today, onOpenPerson, onChanged, tone, showOwner }) {
  return (
    <section className={`set-card today-group ${tone || ''}`}>
      <div className="drawer-label">{title} · {tasks.length}</div>
      {tasks.length === 0 ? <div className="muted today-empty">{empty}</div>
        : tasks.map((t) => <TaskRow key={t.id} t={t} today={today} onOpenPerson={onOpenPerson} onChanged={onChanged} showOwner={showOwner} />)}
    </section>
  )
}

function Team({ team, onView }) {
  if (!team?.length) return null
  const cell = (x, k) => {
    const t = x.targets?.[k]
    return <td key={k} className={t && (x.activity[k] || 0) >= t ? 'met' : ''}>{num(x.activity[k] || 0)}{t ? <span className="muted"> / {num(t)}</span> : ''}</td>
  }
  return (
    <section className="set-card">
      <div className="drawer-label">The team today</div>
      <div className="table-wrap">
        <table className="table today-team">
          <thead><tr><th>Person</th>{TILES.map(([k, l]) => <th key={k}>{l}</th>)}<th>Overdue</th></tr></thead>
          <tbody>
            {team.map((x) => (
              <tr key={x.id}>
                <td><button className="linklike inline" onClick={() => onView(x)}>{x.name || x.email}</button>
                  {x.week ? <div className="muted" style={{ fontSize: 11.5 }}>week {x.week}</div> : null}</td>
                {TILES.map(([k]) => cell(x, k))}
                <td className={x.overdue ? 'late' : ''}>{x.overdue}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default function Today() {
  const me = useMe()
  const [view, setView] = useState(null)          // an admin looking at someone else's day: {id, name}
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [adding, setAdding] = useState(false)
  const [stack, setStack] = useState([])
  const [meta, setMeta] = useState(null)
  const load = () => api.getToday(view?.id || '').then((x) => { setD(x); setErr('') }).catch((e) => setErr(api.errorText(e)))
  useEffect(() => { load() }, [view])  // eslint-disable-line react-hooks/exhaustive-deps
  const switchTo = (v) => { setD(null); setView(v) }   // clear first: never show one person's day under another's name
  useEffect(() => { api.getCrmMeta().then(setMeta).catch(() => {}) }, [])
  if (err) return <div className="banner error">{err}</div>
  if (!d) return <div className="today"><Skeleton h={90} r={10} /><Skeleton h={220} r={10} style={{ marginTop: 16 }} /></div>
  const today = d.date
  const open = (id) => setStack([{ type: 'person', id }])
  const someoneElse = !!view
  const long = new Date(`${today}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
  return (
    <div className="today">
      <motion.header className="today-head" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        <div>
          <h2>{someoneElse ? `${d.user.name || d.user.email}'s day` : long}</h2>
          <div className="muted">
            {d.ramp.has_targets ? d.ramp.note : 'No targets yet: an admin uploads the playbook on the Team page.'}
            {d.ramp.week ? ` Week ${d.ramp.week}.` : ''}
          </div>
        </div>
        <div className="today-head-acts">
          {someoneElse && <button className="btn" onClick={() => switchTo(null)}>Back to my day</button>}
          {!someoneElse && <button className="btn primary" onClick={() => setAdding(true)}>Add task</button>}
        </div>
      </motion.header>
      {adding && <TaskForm onCancel={() => setAdding(false)} onSaved={() => { setAdding(false); load() }} />}
      <Tiles activity={d.activity} ramp={d.ramp} />
      <TaskGroup title="Overdue" tone="late" tasks={d.tasks.overdue} today={today} empty="Nothing overdue."
        onOpenPerson={open} onChanged={load} />
      <TaskGroup title="Due today" tasks={d.tasks.today} today={today}
        empty={d.tasks.counts.upcoming ? 'Nothing due today.' : 'Nothing due today. Log a call on a lead and add a follow-up, or add a task above.'}
        onOpenPerson={open} onChanged={load} />
      <TaskGroup title="Next 7 days" tasks={d.tasks.upcoming} today={today} empty="Nothing scheduled this week."
        onOpenPerson={open} onChanged={load} />
      {isAdmin(me) && !someoneElse && <Team team={d.team} onView={(x) => switchTo({ id: x.id, name: x.name })} />}
      <RecordPanel stack={stack} setStack={setStack} me={me} meta={meta} onClosed={(dirty) => { if (dirty) load() }} />
    </div>
  )
}
