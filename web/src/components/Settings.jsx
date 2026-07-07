import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'

// Read-only view of the campaign's config + the one thing that gates sending:
// whether Apollo is connected. Editing is still done through the wizard /
// the config file — this surface is about knowing the current setup at a glance.
const list = (a) => (a && a.length ? a.join(', ') : '—')

export default function Settings({ campaign }) {
  const [cfg, setCfg] = useState(null)
  const [status, setStatus] = useState(null)
  const [boxes, setBoxes] = useState([])
  const [mailbox, setMailbox] = useState('')
  const [savingMb, setSavingMb] = useState(false)

  useEffect(() => {
    setCfg(null); setStatus(null); setBoxes([]); setMailbox('')
    api.getCampaignConfig(campaign).then(setCfg).catch(() => setCfg({}))
    api.getStatus(campaign).then(setStatus).catch(() => setStatus({}))
    api.getMailboxes(campaign).then((d) => { setBoxes(d.mailboxes || []); setMailbox(d.current || '') }).catch(() => {})
  }, [campaign])

  const changeMailbox = async (id) => {
    const prev = mailbox
    setMailbox(id); setSavingMb(true)
    try { await api.setMailbox(campaign, id) } catch { setMailbox(prev) } finally { setSavingMb(false) }
  }

  if (!cfg || !status) {
    return (
      <div className="settings">
        <Skeleton w="40%" h={18} /><Skeleton w="100%" h={120} r={10} style={{ marginTop: 16 }} />
        <Skeleton w="100%" h={120} r={10} style={{ marginTop: 16 }} />
      </div>
    )
  }

  const offer = cfg.offer || {}
  const icp = cfg.icp || {}
  const voice = cfg.voice || {}
  const verify = cfg.verify || {}
  const sending = cfg.sending || {}
  const win = sending.window || {}
  const connected = !!status.sendable

  const section = (title, rows, extra) => (
    <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="drawer-label">{title}</div>
      {rows.map(([k, v]) => (
        <div className="kv" key={k}><span>{k}</span><b>{v || '—'}</b></div>
      ))}
      {extra}
    </motion.section>
  )

  const winLabel = win.start_hour != null && win.end_hour != null
    ? `${String(win.start_hour).padStart(2, '0')}:00–${String(win.end_hour).padStart(2, '0')}:00${win.weekdays_only ? ' · weekdays only' : ''}`
    : 'any time (24/7)'
  const curBox = boxes.find((b) => b.id === mailbox)

  return (
    <div className="settings">
      <div className="set-note">
        Settings are set when you create a campaign and stored in <code>config/{campaign}.yaml</code>. Edit that file to change them.
      </div>

      {/* connection — the only thing that gates a real send */}
      <motion.section className={`set-card set-conn ${connected ? 'ok' : 'warn'}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="set-conn-icon"><Icon name={connected ? 'check' : 'shield'} size={20} /></div>
        <div className="set-conn-main">
          <div className="set-conn-title">{connected ? 'Apollo connected — sending is enabled' : 'Apollo not connected — sending is disabled'}</div>
          <div className="set-conn-sub">
            {connected
              ? <>Approved leads send through your Apollo sequence from <code>{curBox ? curBox.email : `${sending.mailbox_id?.slice(0, 8)}…`}</code></>
              : <>Set <code>APOLLO_API_KEY</code> plus <code>sending.sequence_id</code> and <code>sending.mailbox_id</code>, then restart the backend. Reviewing and approving work without it.</>}
          </div>
        </div>
      </motion.section>

      {/* which mailbox this campaign sends from — pick from your Apollo accounts */}
      {boxes.length > 0 && (
        <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <div className="drawer-label">Sending mailbox</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
            <select className="src-select" value={mailbox} onChange={(e) => changeMailbox(e.target.value)} disabled={savingMb} style={{ minWidth: 260 }}>
              {!mailbox && <option value="">Choose a mailbox…</option>}
              {boxes.map((b) => (
                <option key={b.id} value={b.id} disabled={!b.active}>{b.email}{b.active ? '' : ' (inactive)'}</option>
              ))}
            </select>
            {savingMb && <span className="spinner" />}
          </div>
          <div className="muted" style={{ marginTop: 10, fontSize: 12.5 }}>
            Approved emails for <b>{campaign}</b> send from this address. Each campaign can use a different mailbox; the change takes effect on the next send.
          </div>
        </motion.section>
      )}

      <div className="set-grid">
        {section('Offer', [
          ['Product', offer.product],
          ['One-liner', offer.one_liner],
          ['Call to action', offer.call_to_action],
          ['Link', offer.link],
        ], offer.value_props?.length ? (
          <ul className="set-bullets">{offer.value_props.map((v, i) => <li key={i}>{v}</li>)}</ul>
        ) : null)}

        {section('Audience', [
          ['Titles', list(icp.titles)],
          ['Industries', list(icp.industries)],
          ['Company size', icp.company_size],
          ['Geographies', list(icp.geographies)],
        ])}

        {section('Voice', [
          ['Tone', voice.tone],
          ['Max words', voice.max_words],
        ], voice.rules?.length ? (
          <ul className="set-bullets">{voice.rules.map((v, i) => <li key={i}>{v}</li>)}</ul>
        ) : null)}

        {section('Sending & safety', [
          ['Platform', 'Apollo'],
          ['Daily cap', sending.daily_cap ? `${sending.daily_cap}/day` : 'unlimited'],
          ['Send window', winLabel],
          ['Drop risky addresses', verify.block_risky ? 'yes' : 'no'],
          ['Require verified email', verify.require_deliverable ? 'yes' : 'no'],
        ])}
      </div>
    </div>
  )
}
