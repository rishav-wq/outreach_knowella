import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'

// Operational settings only. Campaign choices (offer, audience filters, voice,
// sending) are edited in the same dialog as creation — the ⋮ button next to the
// campaign selector — so this page keeps what ISN'T a creation choice:
// connection status, sending health, and the global do-not-contact list.

// Sending health: Apollo's own mailbox scorecards + SPF/DKIM/DMARC checks per
// sending domain + the sequence's bounce rate. Surfaces the problems that
// silently kill deliverability before they show up as ignored campaigns.
function SendingHealth({ campaign }) {
  const [h, setH] = useState(null)
  useEffect(() => { setH(null); api.getSendingHealth(campaign).then(setH).catch(() => setH({ connected: false })) }, [campaign])
  if (!h) return <Skeleton h={100} r={10} style={{ marginTop: 16 }} />
  if (!h.connected) return null
  const tick = (ok, label) => (
    <span className={`badge ${ok ? 's-approved' : 's-invalid'}`} title={ok ? `${label} record found` : `${label} record missing — add it in your DNS`}>{label} {ok ? '✓' : '✗'}</span>
  )
  return (
    <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="drawer-label">Sending health</div>
      {h.sequence?.warn && (
        <div className="banner error" style={{ marginBottom: 12 }}>
          Bounce rate is {h.sequence.bounce_rate}% ({h.sequence.bounced}/{h.sequence.bounced + h.sequence.delivered}) — above the ~2% safety line. Pause sends and turn on “only verified emails” in the audience filters.
        </div>
      )}
      <ul className="health-list">
        {h.mailboxes.map((b) => (
          <li key={b.id}>
            <div className="health-main">
              <code>{b.email}</code>
              {b.placement === 'unhealthy' && <span className="badge s-invalid" title="Apollo's inbox-placement test says emails from this mailbox often land in spam. Warm it up before using it for real sends.">placement: unhealthy</span>}
              {(b.warmup_score === 0 || b.warmup_score === null) && <span className="badge s-held" title="This mailbox isn't warmed up — new mailboxes should send small volumes first.">not warmed</span>}
              {b.hard_bounced > 0 && <span className="badge s-invalid">{b.hard_bounced} hard bounces</span>}
              {b.spam_blocked > 0 && <span className="badge s-invalid">{b.spam_blocked} spam-blocked</span>}
            </div>
            <div className="health-dns">
              {tick(b.dns.spf, 'SPF')} {tick(b.dns.dkim, 'DKIM')} {tick(b.dns.dmarc, 'DMARC')}
              {b.dns.dmarc && b.dns.dmarc_policy && <span className="muted" style={{ fontSize: 11 }}>p={b.dns.dmarc_policy}</span>}
            </div>
          </li>
        ))}
      </ul>
      <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
        SPF/DKIM/DMARC are DNS records on each sending domain — Gmail and Outlook increasingly reject mail from domains missing them. A missing DMARC is fixed with one TXT record (<code>_dmarc.yourdomain</code> → <code>v=DMARC1; p=none; rua=mailto:you@…</code>).
      </div>
    </motion.section>
  )
}

// Global do-not-contact list (compliance): emails + whole domains, enforced at
// pull, pipeline, and send. Shared across all campaigns.
function Suppression() {
  const [items, setItems] = useState(null)
  const [val, setVal] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => { api.getSuppression().then((d) => setItems(d.items || [])).catch(() => setItems([])) }, [])
  const add = async () => {
    setErr('')
    const v = val.trim()
    if (!v) return
    try {
      const r = await api.addSuppression(v)
      setItems(r.items || []); setVal('')
    } catch (e) { setErr(/email address or a domain/.test(String(e.message)) ? 'Enter an email address or a domain like acme.com.' : `Could not add: ${e.message}`) }
  }
  const remove = async (v) => {
    const r = await api.removeSuppression(v)
    setItems(r.items || [])
  }
  return (
    <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="drawer-label">Do not contact — all campaigns</div>
      <div className="muted" style={{ fontSize: 12.5, marginBottom: 12 }}>
        Emails and whole domains here are never pulled, drafted, or sent to — across every campaign. Add anyone who opts out.
      </div>
      <div className="ready-form" style={{ marginBottom: 10 }}>
        <input className="field-input" placeholder="name@company.com or acme.com" value={val}
          onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button className="btn" onClick={add}>Add</button>
      </div>
      {err && <div className="ready-err">{err}</div>}
      {items === null ? <Skeleton w="60%" h={12} /> : items.length === 0
        ? <div className="muted" style={{ fontSize: 12.5 }}>Nothing suppressed yet.</div>
        : (
          <ul className="supp-list">
            {items.map((it) => (
              <li key={it.value}>
                <code>{it.value}</code>
                {it.reason && <span className="muted"> · {it.reason}</span>}
                <button className="icon-btn" title="Remove" onClick={() => remove(it.value)}><Icon name="x" size={13} /></button>
              </li>
            ))}
          </ul>
        )}
    </motion.section>
  )
}

export default function Settings({ campaign }) {
  const [status, setStatus] = useState(null)
  const [boxes, setBoxes] = useState([])
  const [mailboxId, setMailboxId] = useState('')

  useEffect(() => {
    setStatus(null)
    api.getStatus(campaign).then((s) => { setStatus(s); setMailboxId(s.mailbox_id || '') }).catch(() => setStatus({}))
    api.getMailboxes().then((d) => setBoxes(d.mailboxes || [])).catch(() => {})
  }, [campaign])

  if (!status) {
    return (
      <div className="settings">
        <Skeleton w="40%" h={18} /><Skeleton w="100%" h={120} r={10} style={{ marginTop: 16 }} />
        <Skeleton w="100%" h={120} r={10} style={{ marginTop: 16 }} />
      </div>
    )
  }

  const connected = !!status.sendable
  const curBox = boxes.find((b) => b.id === mailboxId)

  return (
    <div className="settings">
      {/* connection — the only thing that gates a real send */}
      <motion.section className={`set-card set-conn ${connected ? 'ok' : 'warn'}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="set-conn-icon"><Icon name={connected ? 'check' : 'shield'} size={20} /></div>
        <div className="set-conn-main">
          <div className="set-conn-title">{connected ? 'Apollo connected — sending is enabled' : 'Apollo not connected — sending is disabled'}</div>
          <div className="set-conn-sub">
            {connected
              ? <>Approved leads send through your Apollo sequence from <code>{curBox ? curBox.email : (mailboxId ? `${mailboxId.slice(0, 8)}…` : '—')}</code></>
              : <>Set <code>APOLLO_API_KEY</code> plus a sequence and mailbox (⋮ next to the campaign → Send). Reviewing and approving work without it.</>}
          </div>
        </div>
      </motion.section>

      <div className="set-note">
        Campaign choices — offer, audience filters, voice, sending — are edited with the <b>⋮ button</b> next to the campaign selector: the same form as campaign creation, pre-filled.
      </div>

      <SendingHealth campaign={campaign} />
      <Suppression />
    </div>
  )
}
