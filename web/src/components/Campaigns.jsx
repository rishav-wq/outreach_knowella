import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'
import RecordPanel from './RecordPanels'
import { SendingConnection, SendingHealth } from './Settings'
import { useMe, isAdmin } from '../me'

// Campaigns as pages (Sid's item 16; docs/knowcrm-requirements-audit.md §5.1): a list of
// every campaign you can see with how it's doing, and each campaign a page with tabs
// (Overview, Sequence, Leads, Review, Activity, Replies). Sequence and Activity are here;
// the other tabs are the existing pages, given the campaign.

const humanize = (s) => (s || '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
const pct = (n, d) => (d ? `${Math.round((n / d) * 1000) / 10}%` : '—')
const when = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

// --- the list -------------------------------------------------------------------------------
export function CampaignList({ onOpen, onNew }) {
  const me = useMe()
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.getCampaignsSummary().then((d) => setRows(d.campaigns)).catch((e) => setErr(api.errorText(e))) }, [])
  const admin = isAdmin(me)
  return (
    <div className="camp-list">
      <div className="camp-list-head">
        <div>
          <h2>Campaigns</h2>
          <div className="muted">{admin ? 'Every campaign, and who works it.' : 'Your campaigns.'} Open one to see its sequence, leads, drafts to review, every email sent and the replies.</div>
        </div>
        <button className="btn primary" onClick={onNew}><Icon name="plus" size={14} /> New campaign</button>
      </div>
      {err && <div className="banner error">{err}</div>}
      {rows === null && !err && <Skeleton h={200} r={10} />}
      {rows && rows.length === 0 && (
        <div className="empty">
          <h3>No campaigns yet</h3>
          <p className="muted">A campaign is who you're reaching (Apollo filters or a CSV), what you're offering, and the emails that go out.</p>
          <div className="empty-actions"><button className="btn primary" onClick={onNew}>Create your first campaign</button></div>
        </div>
      )}
      {rows && rows.length > 0 && (
        <div className="table-wrap">
          <table className="table camp-table">
            <thead>
              <tr>
                <th>Campaign</th>{admin && <th>Owner</th>}<th>Leads</th><th>To review</th><th>Sent</th>
                <th>Replies</th><th>Interested</th><th>Meetings</th><th>Sending</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.name} className="crm-row" onClick={(e) => { if (!e.target.closest('button')) onOpen(c.name) }}>
                  <td>
                    <button className="linklike inline camp-name" onClick={() => onOpen(c.name)}>{c.name}</button>
                    <div className="muted camp-sub">{c.product}{c.steps ? ` · ${c.steps} email${c.steps === 1 ? '' : 's'}` : ''}</div>
                  </td>
                  {admin && <td>{c.owner_name || <span className="muted">Admins</span>}</td>}
                  <td>{c.leads}</td>
                  <td>{c.to_review ? <button className="linklike inline" onClick={() => onOpen(c.name, 'Review')}>{c.to_review}</button> : 0}</td>
                  <td>{c.sent}</td>
                  <td>{c.replies}{c.sent ? <span className="muted"> · {pct(c.replies, c.sent)}</span> : ''}</td>
                  <td>{c.interested}</td>
                  <td>{c.meetings}</td>
                  <td><span className={`badge ${c.sending.wired ? 's-approved' : 's-held'}`}>{c.sending.wired ? 'Connected' : 'Not connected'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// --- a campaign's page: header and tabs ---------------------------------------------------------
export function CampaignFrame({ campaign, tabs, tab, counts = {}, onTab, onAll, onEdit, children }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  const badge = { Leads: total, Review: counts.queued || 0 }
  return (
    <div className="camp-page">
      <div className="camp-head">
        <div>
          <button className="linklike camp-back" onClick={onAll}>← All campaigns</button>
          <h2>{campaign}</h2>
        </div>
        <button className="btn" onClick={onEdit}><Icon name="gear" size={14} /> Edit campaign</button>
      </div>
      <div className="camp-tabs" role="tablist" aria-label="Campaign">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={t.id === tab} className={t.id === tab ? 'on' : ''} onClick={() => onTab(t.id)}>
            {t.label}{badge[t.id] ? <span className={`camp-tab-n ${t.id === 'Review' ? 'hot' : ''}`}>{badge[t.id]}</span> : null}
          </button>
        ))}
      </div>
      <div className="camp-body">{children}</div>
    </div>
  )
}

// --- Sequence -------------------------------------------------------------------------------------
export function Sequence({ campaign, onEdit }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { setD(null); api.getCampaignSequence(campaign).then(setD).catch((e) => setErr(api.errorText(e))) }, [campaign])
  if (err) return <div className="banner error">{err}</div>
  return (
    <div className="cs-seq">
      <SendingConnection campaign={campaign} />
      {!d ? <Skeleton h={220} r={10} /> : (
        <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <div className="cs-head">
            <div>
              <div className="drawer-label">The emails, in order</div>
              <div className="muted cs-note">
                {d.steps.length} email{d.steps.length === 1 ? '' : 's'} over {d.steps[d.steps.length - 1].day} days. Each stops once the lead replies.
                {d.synced ? ' Delivered and reply figures come from Apollo, synced every 6 hours.'
                  : ' Delivered and reply figures appear here once Apollo has sent something and the reply sync has run.'}
              </div>
            </div>
            <button className="btn" onClick={onEdit}>Edit the emails</button>
          </div>
          <ol className="cs-steps">
            {d.steps.map((s) => (
              <li key={s.step} className="cs-step">
                <div className="cs-day"><b>Day {s.day}</b><span className="muted">{s.step === 1 ? 'first email' : `${s.wait_days} day${s.wait_days === 1 ? '' : 's'} later`}</span></div>
                <div className="cs-main">
                  <div className="cs-title">Email {s.step}{s.subject ? <span className="muted"> · {s.subject}</span> : null}</div>
                  {s.written_per_lead
                    ? <div className="cs-tpl muted">Written for each lead from their research. Read and approve them on the Review tab.</div>
                    : s.template ? <div className="cs-tpl">{s.template}</div>
                      : <div className="cs-tpl muted">No template: Apollo sends the sequence's own text for this step.</div>}
                  <div className="cs-stats">
                    <span><b>{s.delivered}</b> delivered</span>
                    <span><b>{s.replied}</b> replied <span className="muted">{pct(s.replied, s.delivered)}</span></span>
                    {s.bounced > 0 && <span className="late"><b>{s.bounced}</b> bounced</span>}
                    {s.failed > 0 && <span className="late"><b>{s.failed}</b> failed</span>}
                    {s.scheduled > 0 && <span><b>{s.scheduled}</b> scheduled</span>}
                    {Object.entries(s.reply_classes).map(([k, v]) => <span key={k} className="tl-chip">{humanize(k)} {v}</span>)}
                  </div>
                </div>
              </li>
            ))}
          </ol>
          {d.untracked_steps.length > 0 && (
            <div className="pub-warn">Apollo also sent step{d.untracked_steps.length === 1 ? '' : 's'} {d.untracked_steps.join(', ')}, which this plan no longer has: the Apollo sequence has more steps than the campaign. Their emails are on the Activity tab.</div>
          )}
        </motion.section>
      )}
      <SendingHealth campaign={campaign} />
    </div>
  )
}

// --- Activity: every email sent -----------------------------------------------------------------------
const OUTCOME = { delivered: ['Delivered', 's-approved'], bounced: ['Bounced', 's-invalid'], failed: ['Failed', 's-invalid'], scheduled: ['Scheduled', 's-new'] }
const FILTERS = [['', 'All'], ['delivered', 'Delivered'], ['replied', 'Replied'], ['bounced', 'Bounced'], ['failed', 'Failed'], ['scheduled', 'Scheduled']]
const PAGE = 100

export function Activity({ campaign }) {
  const me = useMe()
  const [status, setStatus] = useState('')
  const [step, setStep] = useState(0)
  const [steps, setSteps] = useState(1)
  const [d, setD] = useState(null)
  const [more, setMore] = useState(false)
  const [err, setErr] = useState('')
  const [stack, setStack] = useState([])
  const [meta, setMeta] = useState(null)
  const params = (offset) => ({ ...(status ? { status } : {}), ...(step ? { step: String(step) } : {}), offset: String(offset), limit: String(PAGE) })
  useEffect(() => {
    setD(null); setErr('')
    api.getCampaignActivity(campaign, params(0)).then(setD).catch((e) => setErr(api.errorText(e)))
  }, [campaign, status, step])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    api.getCampaignSequence(campaign).then((s) => setSteps(Math.max(s.steps.length, ...s.untracked_steps, 1))).catch(() => {})
    api.getCrmMeta().then(setMeta).catch(() => {})
  }, [campaign])
  const loadMore = async () => {
    setMore(true)
    try {
      const n = await api.getCampaignActivity(campaign, params(d.items.length))
      setD((x) => ({ ...x, items: [...x.items, ...n.items] }))
    } catch (e) { setErr(api.errorText(e)) }
    setMore(false)
  }
  return (
    <div className="camp-activity">
      <div className="act-filters">
        <div className="chip-row" role="group" aria-label="Outcome">
          {FILTERS.map(([k, l]) => <button key={k} className={`chip ${status === k ? 'on' : ''}`} aria-pressed={status === k} onClick={() => setStatus(k)}>{l}</button>)}
        </div>
        <select className="field-input act-step" aria-label="Email" value={step} onChange={(e) => setStep(Number(e.target.value))}>
          <option value={0}>Every email</option>
          {Array.from({ length: steps }, (_, i) => <option key={i + 1} value={i + 1}>Email {i + 1}</option>)}
        </select>
      </div>
      {err && <div className="banner error">{err}</div>}
      {!d && !err && <Skeleton h={240} r={10} />}
      {d && d.items.length === 0 && (
        <div className="empty">
          <h3>{status || step ? 'Nothing matches' : 'No emails sent yet'}</h3>
          <p className="muted">{status || step ? 'Try another filter.'
            : 'Once approved leads are sent and Apollo delivers them, every email shows here, with who it went to and what came of it.'}</p>
        </div>
      )}
      {d && d.items.length > 0 && (
        <>
          <div className="muted act-count">{d.total.toLocaleString()} email{d.total === 1 ? '' : 's'}{d.items.length < d.total ? `, showing ${d.items.length}` : ''}</div>
          <div className="table-wrap">
            <table className="table act-table">
              <thead><tr><th>When</th><th>Lead</th><th>Company</th><th>Email</th><th>Outcome</th><th>Reply</th></tr></thead>
              <tbody>
                {d.items.map((x) => (
                  <tr key={x.id}>
                    <td className="muted">{when(x.delivered_at) || '—'}</td>
                    <td>
                      {x.person_id
                        ? <button className="linklike inline" onClick={() => setStack([{ type: 'person', id: x.person_id }])}>{x.name || x.email}</button>
                        : (x.name || x.email || '—')}
                      <div className="muted act-email">{x.email}</div>
                    </td>
                    <td>{x.company || '—'}</td>
                    <td>Email {x.step || '?'}</td>
                    <td><span className={`badge ${OUTCOME[x.outcome][1]}`}>{OUTCOME[x.outcome][0]}</span></td>
                    <td>{x.replied ? <span className="tl-chip">{humanize(x.reply_class) || 'Replied'}</span> : <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.items.length < d.total && (
            <div className="act-more"><button className="btn" disabled={more} onClick={loadMore}>{more ? 'Loading…' : `Show ${Math.min(PAGE, d.total - d.items.length)} more`}</button></div>
          )}
        </>
      )}
      <RecordPanel stack={stack} setStack={setStack} me={me} meta={meta} />
    </div>
  )
}
