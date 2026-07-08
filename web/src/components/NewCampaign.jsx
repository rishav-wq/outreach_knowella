import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'

// Simple, filter-driven campaign creation: name your offer (pre-filled with
// Knowella's — you always sell the same thing), pick your Apollo audience
// filters from clickable options, choose a mailbox, then Create pulls the
// matching leads from Apollo.
const STEPS = ['Offer', 'Audience', 'Send']
const lines = (s) => s.split('\n').map((x) => x.trim()).filter(Boolean)

import ChipSelect, { TITLE_PRESETS, INDUSTRY_PRESETS, LOCATION_PRESETS, EXCLUDE_PRESETS, SIZE_RANGES, SIZE_MAP, SENIORITY_LEVELS, SENIORITY_MAP, HIRING_PRESETS, EXCLUDE_TITLE_PRESETS } from './ChipSelect'

export default function NewCampaign({ onClose, onCreated }) {
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [mailboxes, setMailboxes] = useState([])
  const [sequences, setSequences] = useState([])
  const [showPitch, setShowPitch] = useState(false)
  const [showAdv, setShowAdv] = useState(false)
  const [showTarget, setShowTarget] = useState(false)
  const [f, setF] = useState({
    name: '',
    // Offer — pre-filled with Knowella's pitch (edit if a campaign needs a different angle)
    product: 'Knowella App Builder',
    one_liner: 'Build safety & compliance workflows without code.',
    value_props: 'Replace paper checklists with mobile inspections\nReal-time compliance dashboards',
    call_to_action: 'a 15-minute demo',
    link: 'https://knowella.com',
    knowledge: 'Knowella serves EHS teams in manufacturing, construction, and logistics.',
    // Audience — Apollo pull filters (arrays, picked from chips)
    titles: [], industries: [], geographies: ['United States'], sizes: [], exclude: [],
    seniorities: ['Director', 'VP', 'C-suite', 'Head', 'Owner'],   // decision-makers by default
    verified_only: true,
    exclude_titles: [], hiring_titles: [], pull_limit: 25,
    // Send
    sequence_id: '', mailbox_id: '', daily_cap: 50,
    // Advanced (sensible defaults; hidden unless expanded)
    tone: 'direct, peer-to-peer, no fake warmth', max_words: 75,
    rules: 'Open with a researched, specific observation about THEIR company.\nNever assert a fact that isn’t in the lead’s research.\nEnd with ONE low-friction interest question — never a demo or meeting ask on the first touch.',
    block_risky: false, require_deliverable: false, max_facts: 12,
  })
  const set = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setF((p) => ({ ...p, [k]: v }))
  }
  const setKey = (k, v) => setF((p) => ({ ...p, [k]: v }))

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  useEffect(() => {
    api.getMailboxes().then((d) => setMailboxes(d.mailboxes || [])).catch(() => {})
    api.getSequences().then((d) => setSequences(d.sequences || [])).catch(() => {})
  }, [])

  const stepValid = () => (step !== 0 ? true : f.name.trim() && f.product.trim())

  const create = async () => {
    setBusy(true); setError(''); setStatus('Creating campaign…')
    try {
      const r = await api.createCampaign({
        name: f.name,
        icp: { titles: f.titles, industries: f.industries, company_size: f.sizes.join(', '), geographies: f.geographies },
        apollo: {
          keywords: f.industries, exclude_keywords: f.exclude,
          employee_ranges: f.sizes.map((l) => SIZE_MAP[l]).filter(Boolean),
          seniorities: f.seniorities.map((l) => SENIORITY_MAP[l]).filter(Boolean),
          exclude_titles: f.exclude_titles,
          email_status: f.verified_only ? ['verified', 'likely to engage'] : [],
          hiring_job_titles: f.hiring_titles,
        },
        offer: { product: f.product, one_liner: f.one_liner, value_props: lines(f.value_props), call_to_action: f.call_to_action, link: f.link },
        knowledge: lines(f.knowledge),
        voice: { tone: f.tone, max_words: Number(f.max_words) || 75, rules: lines(f.rules) },
        research: { max_facts: Number(f.max_facts) || 12 },
        verify: { block_risky: f.block_risky, require_deliverable: f.require_deliverable },
        // No send window — sends any time; the daily cap is the only throttle.
        sending: {
          platform: 'apollo', sequence_id: f.sequence_id, mailbox_id: f.mailbox_id,
          subject_field: 'email_subject', body_field: 'email_body', daily_cap: Number(f.daily_cap) || 0,
        },
      })
      const n = Number(f.pull_limit)
      if (n > 0) {
        setStatus(`Pulling ${n} leads from Apollo…`)
        try { await api.pullApollo(r.created, n) } catch { /* campaign created; leads can be pulled later */ }
      }
      onCreated(r.created)
    } catch (e) {
      setError(String(e.message || e).includes('409') || /exists/.test(String(e.message))
        ? 'A campaign with this name already exists. Pick a different name.'
        : `Could not create the campaign: ${e.message || e}`)
      setBusy(false); setStatus('')
    }
  }

  const field = (label, el, hint) => (
    <div className="field"><label>{label}</label>{el}{hint && <div className="field-hint">{hint}</div>}</div>
  )
  const input = (k, props = {}) => <input className="field-input" value={f[k]} onChange={set(k)} {...props} />
  const area = (k, rows = 3, props = {}) => <textarea className="field-input" rows={rows} value={f[k]} onChange={set(k)} {...props} />
  const check = (k, label) => (
    <label className="field-check"><input type="checkbox" checked={f[k]} onChange={set(k)} /> {label}</label>
  )
  const disclosure = (open, setOpen, label) => (
    <button type="button" className="wizard-more" onClick={() => setOpen(!open)}>
      <Icon name="chevron" size={13} /> {open ? 'Hide' : label}
    </button>
  )

  const body = () => {
    if (step === 0) return (
      <>
        <div className="wizard-note">
          Emails are written from <b>real research on each lead</b> — a specific, sourced opener, kept short, ending in one low-friction question. Your pitch is pre-filled with Knowella’s, so usually you just name the campaign and move on.
        </div>
        {field('Campaign name *', input('name', { placeholder: 'ehs-manufacturing-q3', autoFocus: true }), 'Lowercase letters, numbers, and dashes.')}
        {field('What you’re selling *', input('product', { placeholder: 'Knowella App Builder' }))}
        {field('Link', input('link', { placeholder: 'https://knowella.com' }))}
        {disclosure(showPitch, setShowPitch, 'Fine-tune the pitch (optional)')}
        {showPitch && (
          <>
            {field('One-liner', input('one_liner'))}
            {field('Value props', area('value_props', 3), 'One per line.')}
            {field('Goal — what a reply should lead to', input('call_to_action'), 'The first email won’t ask for this directly — it ends with a soft interest question (“Worth a quick look?”), which converts far better on a cold first touch.')}
          </>
        )}
      </>
    )
    if (step === 1) return (
      <>
        <div className="wizard-note">
          Pick your <b>Apollo filters</b> below — click to select, or type to add your own. On create, we pull the matching companies + contacts straight from Apollo.
        </div>
        {field('Job titles', <ChipSelect presets={TITLE_PRESETS} value={f.titles} onChange={(v) => setKey('titles', v)} placeholder="Type a title + Enter to add" />, 'The roles you’re targeting.')}
        {field('Seniority', <ChipSelect presets={SENIORITY_LEVELS.map(([l]) => l)} value={f.seniorities} onChange={(v) => setKey('seniorities', v)} allowCustom={false} />, 'Keeps the list to decision-makers — cuts juniors and assistants.')}
        {field('Industries / keywords', <ChipSelect presets={INDUSTRY_PRESETS} value={f.industries} onChange={(v) => setKey('industries', v)} placeholder="Type an industry + Enter to add" />, 'Used to find companies in Apollo. Broad words (e.g. “manufacturing”) can match companies that merely mention them — keep it specific.')}
        {field('Company size', <ChipSelect presets={SIZE_RANGES.map(([l]) => l)} value={f.sizes} onChange={(v) => setKey('sizes', v)} allowCustom={false} />, 'Employees. Pick one or more ranges — size strongly predicts reply rate.')}
        {field('Locations', <ChipSelect presets={LOCATION_PRESETS} value={f.geographies} onChange={(v) => setKey('geographies', v)} placeholder="Type a country/region + Enter" />, 'Company HQ. Countries, or type a state/city (e.g. Texas, Chicago).')}
        {check('verified_only', 'Only pull leads with verified email addresses (recommended — fewer bounces, fewer wasted credits)')}
        {disclosure(showTarget, setShowTarget, 'Advanced targeting (optional)')}
        {showTarget && (
          <>
            {field('Actively hiring for roles', <ChipSelect presets={HIRING_PRESETS} value={f.hiring_titles} onChange={(v) => setKey('hiring_titles', v)} placeholder="Type a role + Enter" />, 'Only companies with open job postings for these roles — a strong “they have this pain right now” signal.')}
            {field('Exclude job titles', <ChipSelect presets={EXCLUDE_TITLE_PRESETS} value={f.exclude_titles} onChange={(v) => setKey('exclude_titles', v)} placeholder="Type a title + Enter" />, 'People with these words in their title are skipped.')}
            {field('Exclude company keywords', <ChipSelect presets={EXCLUDE_PRESETS} value={f.exclude} onChange={(v) => setKey('exclude', v)} placeholder="Type a keyword + Enter" />, 'Companies matching these are skipped.')}
          </>
        )}
        {field('How many leads to pull now',
          <select className="field-input" value={f.pull_limit} onChange={set('pull_limit')}>
            <option value={25}>25 leads</option>
            <option value={50}>50 leads</option>
            <option value={100}>100 leads</option>
            <option value={250}>250 leads</option>
            <option value={0}>Don’t pull yet</option>
          </select>,
          'Revealing each lead’s full details uses Apollo credits. Start small.')}
      </>
    )
    return (
      <>
        {field('Send from mailbox', mailboxes.length
          ? <select className="field-input" value={f.mailbox_id} onChange={set('mailbox_id')}>
              <option value="">Choose a mailbox…</option>
              {mailboxes.map((b) => <option key={b.id} value={b.id} disabled={!b.active}>{b.email}{b.active ? '' : ' (inactive)'}</option>)}
            </select>
          : input('mailbox_id', { placeholder: 'connect Apollo, or set later' }),
          'Which of your Apollo mailboxes sends this campaign’s emails.')}
        {field('Apollo sequence', sequences.length
          ? <select className="field-input" value={f.sequence_id} onChange={set('sequence_id')}>
              <option value="">Set later</option>
              {sequences.map((s) => <option key={s.id} value={s.id}>{s.name}{s.archived ? ' (archived)' : ''}</option>)}
            </select>
          : input('sequence_id', { placeholder: 'leave empty to set later' }),
          'Where approved leads are added. Reuse one across campaigns, or make a separate sequence per campaign in Apollo. Sending stays locked until a sequence + mailbox are set; reviewing works without them.')}
        {field('Daily send cap', input('daily_cap', { type: 'number', min: 0 }), '0 = unlimited. Sends any time of day — the cap is the only throttle.')}
        {disclosure(showAdv, setShowAdv, 'Advanced settings (optional)')}
        {showAdv && (
          <>
            {field('Tone', input('tone'))}
            {field('Max words per email', input('max_words', { type: 'number', min: 30, max: 300 }))}
            {field('Writing rules', area('rules', 4), 'One per line. The quality gate holds drafts that break them.')}
            {field('Known product truths', area('knowledge', 2), 'One per line. The only product claims the writer may rely on.')}
            {check('block_risky', 'Drop risky / catch-all addresses during research')}
            {check('require_deliverable', 'Only send to positively verified addresses')}
            {field('Max research facts per lead', input('max_facts', { type: 'number', min: 3, max: 30 }))}
          </>
        )}
      </>
    )
  }

  const isLast = step === STEPS.length - 1
  const createLabel = Number(f.pull_limit) > 0 ? `Create & pull ${f.pull_limit}` : 'Create campaign'

  return (
    <motion.div className="modal-scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      <motion.div className="wizard" role="dialog" aria-label="New campaign" onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: 24, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 12 }}
        transition={{ type: 'spring', stiffness: 380, damping: 34 }}>
        <div className="wizard-head">
          <div className="wizard-title">New campaign</div>
          <button className="icon-btn wizard-close" onClick={onClose} aria-label="Close"><Icon name="x" size={18} /></button>
        </div>
        <div className="wizard-steps">
          {STEPS.map((s, i) => (
            <button key={s} className={`wizard-step ${i === step ? 'on' : ''} ${i < step ? 'done' : ''}`}
              onClick={() => i < step && setStep(i)} disabled={i > step}>
              <span className="n">{String(i + 1).padStart(2, '0')}</span> {s}
            </button>
          ))}
        </div>
        <div className="wizard-body">
          {error && <div className="banner error">{error}</div>}
          {body()}
        </div>
        <div className="wizard-foot">
          {step > 0 && <button className="btn" onClick={() => setStep(step - 1)} disabled={busy}>Back</button>}
          <span style={{ flex: 1 }} />
          {busy && status && <span className="muted" style={{ marginRight: 10 }}>{status}</span>}
          {!isLast
            ? <button className="btn primary" disabled={!stepValid()} onClick={() => setStep(step + 1)}>Continue</button>
            : <button className="btn primary" disabled={busy} onClick={create}>
                {busy ? <><span className="spinner" /> Working…</> : createLabel}
              </button>}
        </div>
      </motion.div>
    </motion.div>
  )
}
