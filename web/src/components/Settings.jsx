import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'
import { useMe, isAdmin, canSales, canMarketing } from '../me'

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

// Marketing engine (Postmark broadcast stream) — connection state + a one-click
// test send, so the pipe is proven against your own inbox before any blast exists.
function MarketingSending() {
  const [st, setSt] = useState(null)
  const [to, setTo] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)   // {ok, text}
  useEffect(() => { api.getMarketingStatus().then(setSt).catch(() => setSt({ connected: false })) }, [])
  const test = async () => {
    setBusy(true); setMsg(null)
    try {
      await api.sendMarketingTest(to.trim())
      setMsg({ ok: true, text: `Test sent to ${to.trim()} — check the inbox (and spam, first time).` })
    } catch (e) {
      setMsg({ ok: false, text: `Could not send: ${String(e.message).slice(0, 220)}` })
    } finally { setBusy(false) }
  }
  if (!st) return null
  return (
    <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="drawer-label">Marketing email — Postmark</div>
      {st.connected ? (
        <>
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 12 }}>
            Connected. Bulk sends (newsletters, announcements) go out via Postmark&apos;s <b>{st.stream}</b> stream,
            from <code>{st.from || 'MARKETING_FROM not set'}</code> — fully separate from your sales mailboxes.
          </div>
          <div className="ready-form">
            <input className="field-input" placeholder="you@knowella.com" value={to}
              onChange={(e) => setTo(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && to.includes('@') && test()} />
            <button className="btn primary" disabled={busy || !to.includes('@')} onClick={test}>
              {busy ? <><span className="spinner" /> Sending…</> : 'Send test email'}
            </button>
          </div>
          {msg && <div className={`banner ${msg.ok ? '' : 'error'}`} style={{ marginTop: 12, marginBottom: 0 }}>{msg.text}</div>}
        </>
      ) : (
        <div className="muted" style={{ fontSize: 12.5 }}>
          Not connected. Set <code>POSTMARK_SERVER_TOKEN</code> and <code>MARKETING_FROM</code> (a sender verified in
          Postmark) in <code>.env</code>, then restart the backend.
        </div>
      )}
    </motion.section>
  )
}

// Token for the LinkedIn-capture browser extension. Clerk sessions can't travel
// into an extension, so it authenticates with this instead. Only the hash is
// stored server-side — the token is shown once, here, on generation.
function LinkedInCapture() {
  const [data, setData] = useState(null)      // {tokens, legacy}
  const [token, setToken] = useState('')      // plaintext, only right after generating
  const [label, setLabel] = useState('')
  const [copied, setCopied] = useState(false)

  const load = () => api.getCaptureToken().then(setData).catch(() => setData({ tokens: [] }))
  useEffect(() => { load() }, [])

  const generate = async () => {
    const r = await api.createCaptureToken(label.trim())
    setToken(r.token); setCopied(false); setLabel('')
    load()
  }
  const revoke = async (t) => {
    if (!window.confirm(`Revoke ${t.label || 'this token'}? That person's extension stops working; everyone else is unaffected.`)) return
    await api.revokeCaptureToken(t.id)
    load()
  }
  const revokeLegacy = async () => {
    if (!window.confirm('Retire the old shared token? Anyone still using it must switch to a personal one.')) return
    await api.revokeLegacyCaptureToken()
    load()
  }
  const copy = () => { navigator.clipboard.writeText(token).then(() => setCopied(true)).catch(() => {}) }
  const when = (s) => (s ? new Date(s).toLocaleDateString() : '')

  const tokens = data?.tokens || []
  return (
    <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="drawer-label">LinkedIn capture extension</div>
      <div className="muted" style={{ fontSize: 12.5, marginBottom: 12 }}>
        The browser extension captures commenters and reactors from a LinkedIn post into a campaign
        (enriched via Apollo, deduped, landing as normal leads for review). Give <b>each person their
        own token</b> — issuing or revoking one never affects anybody else&apos;s.
      </div>

      {token && (
        <div className="token-reveal">
          <code className="token-value">{token}</code>
          <button className="btn" onClick={copy}>{copied ? 'Copied ✓' : 'Copy'}</button>
          <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            Shown once — only its hash is stored. Send it to that person for the extension&apos;s ⚙ settings.
          </div>
        </div>
      )}

      {data === null ? <Skeleton w="60%" h={12} /> : (
        <>
          {tokens.length > 0 && (
            <ul className="supp-list" style={{ marginBottom: 10 }}>
              {tokens.map((t) => (
                <li key={t.id}>
                  <b>{t.label}</b>
                  <span className="muted">
                    {' · issued ' + when(t.created_at)}
                    {t.last_used_at ? ` · last used ${when(t.last_used_at)}` : ' · never used'}
                  </span>
                  <button className="icon-btn" title="Revoke this person's token" onClick={() => revoke(t)}>
                    <Icon name="x" size={13} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {data.legacy && (
            <div className="banner" style={{ marginBottom: 10 }}>
              An old <b>shared</b> token is still active — the one that broke for everyone whenever it was
              regenerated. Give each person a token above, then retire it.
              <button className="linklike" style={{ display: 'inline', marginLeft: 8 }} onClick={revokeLegacy}>Retire it</button>
            </div>
          )}
          {tokens.length === 0 && !data.legacy && (
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>No tokens yet.</div>
          )}
        </>
      )}

      <div className="ready-form">
        <input className="field-input" placeholder="Who is this for? e.g. Sid" value={label}
          onChange={(e) => setLabel(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && generate()} />
        <button className="btn primary" onClick={generate}>Generate token</button>
      </div>
    </motion.section>
  )
}

// Global do-not-contact list (compliance): emails + whole domains, enforced at
// pull, pipeline, and send. Shared across all campaigns.
function Suppression() {
  const admin = isAdmin(useMe())   // anyone can add a do-not-contact; only admins lift one
  const [items, setItems] = useState(null)
  const [val, setVal] = useState('')
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  useEffect(() => { api.getSuppression().then((d) => setItems(d.items || [])).catch(() => setItems([])) }, [])
  const add = async () => {
    setErr(''); setNote('')
    const v = val.trim()
    if (!v) return
    try {
      const r = await api.addSuppression(v)
      setItems(r.items || []); setVal('')
      if (r.stopped_in_apollo > 0) setNote(`Also cancelled the remaining scheduled Apollo emails for ${r.stopped_in_apollo} enrolled ${r.stopped_in_apollo === 1 ? 'contact' : 'contacts'}.`)
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
      {note && <div className="banner" style={{ marginBottom: 10 }}>{note}</div>}
      {items === null ? <Skeleton w="60%" h={12} /> : items.length === 0
        ? <div className="muted" style={{ fontSize: 12.5 }}>Nothing suppressed yet.</div>
        : (
          <ul className="supp-list">
            {items.map((it) => (
              <li key={it.value}>
                <code>{it.value}</code>
                {it.reason && <span className="muted"> · {it.reason}</span>}
                {admin && <button className="icon-btn" title="Remove" onClick={() => remove(it.value)}><Icon name="x" size={13} /></button>}
              </li>
            ))}
          </ul>
        )}
    </motion.section>
  )
}

// Existing Knowella customers. Anyone at one of these domains is never added to a
// campaign (an import skips them and says so), and their company shows as a Customer.
// Admins keep the list until it can come straight from Knowella's own data.
function Customers() {
  const admin = isAdmin(useMe())
  const [items, setItems] = useState(null)
  const [text, setText] = useState('')
  const [name, setName] = useState('')
  const [msg, setMsg] = useState(null)
  const load = () => api.listCustomers().then(setItems).catch(() => setItems([]))
  useEffect(() => { load() }, [])
  const add = async () => {
    setMsg(null)
    const domains = text.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean)
    if (!domains.length) return
    try {
      const r = await api.addCustomers(domains, name.trim())
      setMsg({ ok: true, text: `Added ${r.added.length}${r.ignored ? ` (${r.ignored} already listed, personal-mail or not a domain)` : ''}.` })
      setText(''); setName(''); load()
    } catch (e) { setMsg({ ok: false, text: api.errorText(e) }) }
  }
  const remove = async (d) => {
    if (!window.confirm(`Take ${d} off the customer list? People there can then be added to campaigns.`)) return
    await api.removeCustomer(d); load()
  }
  return (
    <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="drawer-label">Existing customers: never cold-emailed</div>
      <div className="muted" style={{ fontSize: 12.5, marginBottom: 12 }}>
        Anyone at these companies is never added to a campaign, whoever imports them, and the company shows as a Customer.
        {admin ? ' Add each customer’s web domain.' : ' An admin keeps this list.'}
      </div>
      {admin && (
        <>
          <div className="ready-form" style={{ marginBottom: 8 }}>
            <input className="field-input" aria-label="Domains" placeholder="acme.com, kehe.com (one or more)" value={text}
              onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
            <input className="field-input" aria-label="Customer name" placeholder="Name (optional)" value={name} style={{ maxWidth: 200 }}
              onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
            <button className="btn" onClick={add}>Add</button>
          </div>
          {msg && <div className={`banner ${msg.ok ? '' : 'error'}`} style={{ marginBottom: 10 }}>{msg.text}</div>}
        </>
      )}
      {items === null ? <Skeleton w="60%" h={12} /> : items.length === 0
        ? <div className="muted" style={{ fontSize: 12.5 }}>No customers listed yet.</div>
        : (
          <ul className="supp-list">
            {items.map((c) => (
              <li key={c.domain}>
                <code>{c.domain}</code>
                {c.name && <span className="muted"> · {c.name}</span>}
                {admin && <button className="icon-btn" title="Remove" aria-label={`Remove ${c.domain}`} onClick={() => remove(c.domain)}><Icon name="x" size={13} /></button>}
              </li>
            ))}
          </ul>
        )}
    </motion.section>
  )
}

// The Apollo reply sync (admins): every few hours it reads every message of every
// campaign's sequence, so replies count with Apollo's own class and stages move.
function ReplySync() {
  const [st, setSt] = useState(null)
  const [msg, setMsg] = useState('')
  const load = () => api.getReplySync().then(setSt).catch(() => setSt({}))
  useEffect(() => { load() }, [])
  const now = async () => {
    setMsg('')
    try {
      const r = await api.runReplySync()
      setMsg(r.started ? 'Started. It takes a few minutes; refresh this page to see the result.' : (r.message || 'Not started.'))
      setTimeout(load, 4000)
    } catch (e) { setMsg(api.errorText(e)) }
  }
  if (!st) return null
  const l = st.last || {}
  const when = l.at ? new Date(l.at).toLocaleString() : ''
  const replies = ['interested', 'not_interested', 'wrong_person', 'opt_out', 'other']
    .map((k) => [k, l[`reply_${k}`] || 0]).filter(([, n]) => n)
  return (
    <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="drawer-label">Replies from Apollo</div>
      <div className="muted" style={{ fontSize: 12.5, marginBottom: 12 }}>
        Every {st.every_hours} hours the app reads every message of every campaign’s Apollo sequence: which step went out
        when, who replied and how Apollo classed the reply (interested, not interested, wrong person…), and bounces.
        Lead stages and campaign outcomes follow from it. Apollo doesn’t share the reply text itself.
      </div>
      {l.at ? (
        <div style={{ fontSize: 13, marginBottom: 10 }}>
          Last run {when}: {l.messages || 0} messages across {l.sequences || 0} sequence{l.sequences === 1 ? '' : 's'}
          {l.new_replies ? `, ${l.new_replies} new repl${l.new_replies === 1 ? 'y' : 'ies'}` : ''}
          {replies.length ? ` (${replies.map(([k, n]) => `${n} ${k.replace('_', ' ')}`).join(', ')})` : ''}
          {l.bounced ? `, ${l.bounced} bounced` : ''}.
          {l.stopped && <div className="pub-warn">Stopped early: {l.stopped}.</div>}
        </div>
      ) : <div className="muted" style={{ fontSize: 13, marginBottom: 10 }}>{st.running ? 'Running now…' : 'Not run yet.'}</div>}
      <button className="btn" onClick={now} disabled={st.running}>{st.running ? 'Running…' : 'Sync now'}</button>
      {msg && <div className="banner" style={{ marginTop: 10, marginBottom: 0 }}>{msg}</div>}
    </motion.section>
  )
}

export default function Settings({ campaign }) {
  const me = useMe()
  // The sending side belongs to a campaign: shown to sales and admins who have one.
  const salesSide = canSales(me) && !!campaign
  const [status, setStatus] = useState(null)
  const [boxes, setBoxes] = useState([])
  const [mailboxId, setMailboxId] = useState('')

  useEffect(() => {
    if (!salesSide) return
    setStatus(null)
    api.getStatus(campaign).then((s) => { setStatus(s); setMailboxId(s.mailbox_id || '') }).catch(() => setStatus({}))
    api.getMailboxes().then((d) => setBoxes(d.mailboxes || [])).catch(() => {})
  }, [campaign, salesSide])

  if (!salesSide) {
    return (
      <div className="settings">
        {canMarketing(me) && <MarketingSending />}
        <LinkedInCapture />
        <Suppression />
        {canSales(me) && <Customers />}
      </div>
    )
  }

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
              : isAdmin(me)
                ? <>Set <code>APOLLO_API_KEY</code> plus a sequence and mailbox (⋮ next to the campaign → Send). Reviewing and approving work without it.</>
                : <>An admin connects this campaign’s mailbox and Apollo sequence. Reviewing and approving work without it.</>}
          </div>
        </div>
      </motion.section>

      <div className="set-note">
        Campaign choices — offer, audience filters, voice, sending — are edited with the <b>⋮ button</b> next to the campaign selector: the same form as campaign creation, pre-filled.
      </div>

      <SendingHealth campaign={campaign} />
      {canMarketing(me) && <MarketingSending />}
      <LinkedInCapture />
      <Suppression />
      <Customers />
      {isAdmin(me) && <ReplySync />}
    </div>
  )
}
