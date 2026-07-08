import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'
import ChipSelect, { TITLE_PRESETS, INDUSTRY_PRESETS, LOCATION_PRESETS, EXCLUDE_PRESETS, SIZE_RANGES, SENIORITY_LEVELS, SENIORITY_MAP, HIRING_PRESETS, EXCLUDE_TITLE_PRESETS } from './ChipSelect'

// Editable campaign settings — the same fields (and chip pickers) as the New
// campaign wizard, pre-filled with this campaign's config. Edit anything, Save.
const lines = (s) => s.split('\n').map((x) => x.trim()).filter(Boolean)
const SIZE_LABELS = SIZE_RANGES.map(([l]) => l)
const LABEL_BY_RANGE = Object.fromEntries(SIZE_RANGES.map(([l, v]) => [v, l]))
const LABEL_BY_SENIORITY = Object.fromEntries(SENIORITY_LEVELS.map(([l, v]) => [v, l]))

export default function Settings({ campaign }) {
  const [status, setStatus] = useState(null)
  const [boxes, setBoxes] = useState([])
  const [seqs, setSeqs] = useState([])
  const [f, setF] = useState(null)          // editable form state (null = loading)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    setF(null); setStatus(null); setMsg('')
    api.getStatus(campaign).then(setStatus).catch(() => setStatus({}))
    api.getMailboxes().then((d) => setBoxes(d.mailboxes || [])).catch(() => {})
    api.getSequences().then((d) => setSeqs(d.sequences || [])).catch(() => {})
    api.getCampaignConfig(campaign).then((cfg) => {
      const icp = cfg.icp || {}, ap = cfg.apollo || {}, offer = cfg.offer || {}
      const voice = cfg.voice || {}, verify = cfg.verify || {}, send = cfg.sending || {}
      setF({
        product: offer.product || '', one_liner: offer.one_liner || '',
        value_props: (offer.value_props || []).join('\n'),
        call_to_action: offer.call_to_action || '', link: offer.link || '',
        knowledge: (cfg.knowledge || []).join('\n'),
        titles: icp.titles || [], industries: icp.industries || [],
        geographies: icp.geographies || [],
        sizes: (ap.employee_ranges || []).map((r) => LABEL_BY_RANGE[r] || r),
        company_size: icp.company_size || '',
        exclude: ap.exclude_keywords || [],
        seniorities: (ap.seniorities || []).map((v) => LABEL_BY_SENIORITY[v] || v),
        verified_only: (ap.email_status || []).length > 0,
        exclude_titles: ap.exclude_titles || [],
        hiring_titles: ap.hiring_job_titles || [],
        tone: voice.tone || '', max_words: voice.max_words || 75,
        rules: (voice.rules || []).join('\n'),
        block_risky: !!verify.block_risky, require_deliverable: !!verify.require_deliverable,
        sequence_id: send.sequence_id || '', mailbox_id: send.mailbox_id || '',
        daily_cap: send.daily_cap ?? 50,
      })
    }).catch(() => setF(null))
  }, [campaign])

  const set = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setF((p) => ({ ...p, [k]: v }))
  }
  const setKey = (k, v) => setF((p) => ({ ...p, [k]: v }))

  const save = async () => {
    setBusy(true); setMsg('')
    try {
      const sizeMap = Object.fromEntries(SIZE_RANGES)
      await api.updateCampaign(campaign, {
        icp: {
          titles: f.titles, industries: f.industries, geographies: f.geographies,
          company_size: f.sizes.length ? f.sizes.join(', ') : f.company_size,
        },
        apollo: {
          keywords: f.industries, exclude_keywords: f.exclude,
          employee_ranges: f.sizes.map((l) => sizeMap[l]).filter(Boolean),
          seniorities: f.seniorities.map((l) => SENIORITY_MAP[l]).filter(Boolean),
          exclude_titles: f.exclude_titles,
          email_status: f.verified_only ? ['verified', 'likely to engage'] : [],
          hiring_job_titles: f.hiring_titles,
        },
        offer: {
          product: f.product, one_liner: f.one_liner, value_props: lines(f.value_props),
          call_to_action: f.call_to_action, link: f.link,
        },
        knowledge: lines(f.knowledge),
        voice: { tone: f.tone, max_words: Number(f.max_words) || 75, rules: lines(f.rules) },
        verify: { block_risky: f.block_risky, require_deliverable: f.require_deliverable },
        sending: { sequence_id: f.sequence_id, mailbox_id: f.mailbox_id, daily_cap: Number(f.daily_cap) || 0 },
      })
      setMsg('Saved. New drafts and pulls use the updated settings.')
    } catch (e) {
      setMsg(`Could not save: ${e.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  if (!f || !status) {
    return (
      <div className="settings">
        <Skeleton w="40%" h={18} /><Skeleton w="100%" h={120} r={10} style={{ marginTop: 16 }} />
        <Skeleton w="100%" h={120} r={10} style={{ marginTop: 16 }} />
      </div>
    )
  }

  const connected = !!status.sendable
  const curBox = boxes.find((b) => b.id === f.mailbox_id)

  const field = (label, el, hint) => (
    <div className="field"><label>{label}</label>{el}{hint && <div className="field-hint">{hint}</div>}</div>
  )
  const input = (k, props = {}) => <input className="field-input" value={f[k]} onChange={set(k)} {...props} />
  const area = (k, rows = 3) => <textarea className="field-input" rows={rows} value={f[k]} onChange={set(k)} />
  const check = (k, label) => (
    <label className="field-check"><input type="checkbox" checked={f[k]} onChange={set(k)} /> {label}</label>
  )
  const card = (title, children) => (
    <motion.section className="set-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className="drawer-label">{title}</div>
      {children}
    </motion.section>
  )

  return (
    <div className="settings">
      {/* connection — the only thing that gates a real send */}
      <motion.section className={`set-card set-conn ${connected ? 'ok' : 'warn'}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="set-conn-icon"><Icon name={connected ? 'check' : 'shield'} size={20} /></div>
        <div className="set-conn-main">
          <div className="set-conn-title">{connected ? 'Apollo connected — sending is enabled' : 'Apollo not connected — sending is disabled'}</div>
          <div className="set-conn-sub">
            {connected
              ? <>Approved leads send through your Apollo sequence from <code>{curBox ? curBox.email : f.mailbox_id}</code></>
              : <>Set <code>APOLLO_API_KEY</code> plus a sequence and mailbox below. Reviewing and approving work without it.</>}
          </div>
        </div>
      </motion.section>

      <div className="set-grid">
        {card('Offer', (
          <>
            {field('Product', input('product'))}
            {field('One-liner', input('one_liner'))}
            {field('Value props', area('value_props', 3), 'One per line.')}
            {field('Goal — what a reply should lead to', input('call_to_action'), 'The first email ends with a soft interest question, not this ask.')}
            {field('Link', input('link'))}
            {field('Known product truths', area('knowledge', 3), 'One per line. The only product claims the writer may rely on.')}
          </>
        ))}

        {card('Audience · Apollo filters', (
          <>
            {field('Job titles', <ChipSelect presets={TITLE_PRESETS} value={f.titles} onChange={(v) => setKey('titles', v)} placeholder="Type a title + Enter" />)}
            {field('Seniority', <ChipSelect presets={SENIORITY_LEVELS.map(([l]) => l)} value={f.seniorities} onChange={(v) => setKey('seniorities', v)} allowCustom={false} />, 'Keeps the list to decision-makers.')}
            {field('Industries / keywords', <ChipSelect presets={INDUSTRY_PRESETS} value={f.industries} onChange={(v) => setKey('industries', v)} placeholder="Type an industry + Enter" />)}
            {field('Company size', <ChipSelect presets={SIZE_LABELS} value={f.sizes} onChange={(v) => setKey('sizes', v)} allowCustom={false} />,
              f.sizes.length === 0 && f.company_size ? `Currently: ${f.company_size} (pick ranges above to change)` : 'Employees. Pick one or more ranges — size strongly predicts reply rate.')}
            {field('Locations', <ChipSelect presets={LOCATION_PRESETS} value={f.geographies} onChange={(v) => setKey('geographies', v)} placeholder="Type a country/state + Enter" />, 'Company HQ.')}
            {check('verified_only', 'Only pull leads with verified email addresses (recommended)')}
            {field('Actively hiring for roles', <ChipSelect presets={HIRING_PRESETS} value={f.hiring_titles} onChange={(v) => setKey('hiring_titles', v)} placeholder="Type a role + Enter" />, 'Only companies with open postings for these roles — a strong buying signal.')}
            {field('Exclude job titles', <ChipSelect presets={EXCLUDE_TITLE_PRESETS} value={f.exclude_titles} onChange={(v) => setKey('exclude_titles', v)} placeholder="Type a title + Enter" />)}
            {field('Exclude company keywords', <ChipSelect presets={EXCLUDE_PRESETS} value={f.exclude} onChange={(v) => setKey('exclude', v)} placeholder="Type a keyword + Enter" />, 'Changes apply to the next Apollo pull.')}
          </>
        ))}

        {card('Voice', (
          <>
            {field('Tone', input('tone'))}
            {field('Max words per email', input('max_words', { type: 'number', min: 30, max: 300 }))}
            {field('Writing rules', area('rules', 4), 'One per line. The quality gate holds drafts that break them.')}
          </>
        ))}

        {card('Sending & safety', (
          <>
            {field('Send from mailbox', boxes.length
              ? <select className="field-input" value={f.mailbox_id} onChange={set('mailbox_id')}>
                  <option value="">Choose a mailbox…</option>
                  {boxes.map((b) => <option key={b.id} value={b.id} disabled={!b.active}>{b.email}{b.active ? '' : ' (inactive)'}</option>)}
                </select>
              : input('mailbox_id'))}
            {field('Apollo sequence', seqs.length
              ? <select className="field-input" value={f.sequence_id} onChange={set('sequence_id')}>
                  <option value="">Set later</option>
                  {seqs.map((s) => <option key={s.id} value={s.id}>{s.name}{s.archived ? ' (archived)' : ''}</option>)}
                </select>
              : input('sequence_id'))}
            {field('Daily send cap', input('daily_cap', { type: 'number', min: 0 }), '0 = unlimited. Sends any time of day — the cap is the only throttle.')}
            {check('block_risky', 'Drop risky / catch-all addresses during research')}
            {check('require_deliverable', 'Only send to positively verified addresses')}
          </>
        ))}
      </div>

      <div className="set-savebar">
        {msg && <span className={/Could not/.test(msg) ? 'ready-err' : 'muted'}>{msg}</span>}
        <button className="btn primary" onClick={save} disabled={busy}>
          {busy ? <><span className="spinner" /> Saving…</> : 'Save changes'}
        </button>
      </div>
    </div>
  )
}
