import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'

// Linear campaign-creation wizard. Numbered steps are a true sequence:
// each later step depends on the earlier answers.
const STEPS = ['Basics', 'Audience', 'Voice & truth', 'Sending & safety', 'Review']

const lines = (s) => s.split('\n').map((x) => x.trim()).filter(Boolean)
const csv = (s) => s.split(',').map((x) => x.trim()).filter(Boolean)

export default function NewCampaign({ onClose, onCreated }) {
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [f, setF] = useState({
    name: '', product: '', one_liner: '', value_props: '', call_to_action: 'a 15-minute demo', link: '',
    titles: '', industries: '', company_size: '', geographies: 'United States',
    apollo_keywords: '', apollo_exclude: '',
    tone: 'direct, peer-to-peer, no fake warmth', max_words: 90,
    rules: 'Open with a researched, specific observation about THEIR company.\nNever assert a fact that isn’t in the lead’s research.\nExactly one clear call to action.',
    knowledge: '',
    sequence_id: '', mailbox_id: '', daily_cap: 50, start_hour: 8, end_hour: 17, weekdays_only: true,
    block_risky: false, require_deliverable: false, max_facts: 12,
  })
  const set = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setF((p) => ({ ...p, [k]: v }))
  }

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const stepValid = () => {
    if (step === 0) return f.name.trim() && f.product.trim()
    return true
  }

  const create = async () => {
    setBusy(true); setError('')
    try {
      const r = await api.createCampaign({
        name: f.name,
        icp: {
          titles: csv(f.titles), industries: csv(f.industries),
          company_size: f.company_size, geographies: csv(f.geographies),
        },
        apollo: {
          keywords: csv(f.apollo_keywords),
          exclude_keywords: csv(f.apollo_exclude),
        },
        offer: {
          product: f.product, one_liner: f.one_liner, value_props: lines(f.value_props),
          call_to_action: f.call_to_action, link: f.link,
        },
        knowledge: lines(f.knowledge),
        voice: { tone: f.tone, max_words: Number(f.max_words) || 90, rules: lines(f.rules) },
        research: { max_facts: Number(f.max_facts) || 12 },
        verify: { block_risky: f.block_risky, require_deliverable: f.require_deliverable },
        sending: {
          platform: 'apollo',
          sequence_id: f.sequence_id,
          mailbox_id: f.mailbox_id,
          subject_field: 'email_subject',
          body_field: 'email_body',
          daily_cap: Number(f.daily_cap) || 0,
          window: {
            start_hour: Number(f.start_hour), end_hour: Number(f.end_hour),
            weekdays_only: f.weekdays_only,
          },
        },
      })
      onCreated(r.created)
    } catch (e) {
      setError(String(e.message || e).includes('409') || /exists/.test(String(e.message))
        ? 'A campaign with this name already exists. Pick a different name.'
        : `Could not create the campaign: ${e.message || e}`)
      setBusy(false)
    }
  }

  const field = (label, el, hint) => (
    <div className="field">
      <label>{label}</label>
      {el}
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  )
  const input = (k, props = {}) => <input className="field-input" value={f[k]} onChange={set(k)} {...props} />
  const area = (k, rows = 3, props = {}) => <textarea className="field-input" rows={rows} value={f[k]} onChange={set(k)} {...props} />
  const check = (k, label) => (
    <label className="field-check">
      <input type="checkbox" checked={f[k]} onChange={set(k)} /> {label}
    </label>
  )

  const body = () => {
    if (step === 0) return (
      <>
        {field('Campaign name *', input('name', { placeholder: 'ehs-manufacturing-q3', autoFocus: true }), 'Lowercase letters, numbers, and dashes work best — this names the config file.')}
        {field('Product *', input('product', { placeholder: 'Knowella App Builder' }))}
        {field('One-liner', input('one_liner', { placeholder: 'Build safety & compliance workflows without code.' }))}
        {field('Value props', area('value_props', 3, { placeholder: 'Replace paper checklists with mobile inspections\nReal-time compliance dashboards' }), 'One per line.')}
        {field('Call to action', input('call_to_action'))}
        {field('Link', input('link', { placeholder: 'https://knowella.com' }))}
      </>
    )
    if (step === 1) return (
      <>
        {field('Target titles', input('titles', { placeholder: 'Head of EHS, Safety Manager, Operations Director' }), 'Comma-separated.')}
        {field('Industries', input('industries', { placeholder: 'Manufacturing, Construction, Logistics' }), 'Comma-separated.')}
        {field('Company size', input('company_size', { placeholder: '50-500' }))}
        {field('Geographies', input('geographies'), 'Comma-separated.')}
        {field('Apollo keywords', input('apollo_keywords', { placeholder: 'logistics, trucking, freight' }), 'Comma-separated industry/keyword tags for the Apollo pull. Defaults to Industries above if left blank.')}
        {field('Exclude keywords', input('apollo_exclude', { placeholder: 'computer software, information technology' }), 'Comma-separated. Companies matching these are left out of the Apollo pull.')}
      </>
    )
    if (step === 2) return (
      <>
        {field('Tone', input('tone'))}
        {field('Max words per email', input('max_words', { type: 'number', min: 30, max: 300 }))}
        {field('Writing rules', area('rules', 4), 'One per line. The quality gate holds drafts that break them.')}
        {field('Known truths about your product', area('knowledge', 3, { placeholder: 'Knowella serves EHS teams in manufacturing and construction.' }), 'One per line. The only product claims the writer may rely on — everything else must come from lead research.')}
      </>
    )
    if (step === 3) return (
      <>
        {field('Apollo sequence ID', input('sequence_id', { placeholder: 'leave empty to set later' }), 'The Apollo sequence approved leads are added to. Sending stays locked until this and a mailbox are set; reviewing works without them.')}
        {field('Apollo mailbox ID', input('mailbox_id', { placeholder: 'email_account id to send from' }), 'Which of your Apollo mailboxes sends the emails.')}
        {field('Daily send cap', input('daily_cap', { type: 'number', min: 0 }), '0 = unlimited. Approved leads over the cap stay queued until tomorrow.')}
        <div className="field-row">
          {field('Send from (hour)', input('start_hour', { type: 'number', min: 0, max: 23 }))}
          {field('Until (hour)', input('end_hour', { type: 'number', min: 1, max: 24 }))}
        </div>
        {check('weekdays_only', 'Weekdays only')}
        {check('block_risky', 'Drop risky / catch-all addresses during research')}
        {check('require_deliverable', 'Only send to positively verified addresses')}
        {field('Max research facts per lead', input('max_facts', { type: 'number', min: 3, max: 30 }), 'Top facts by confidence; more facts = more tokens.')}
      </>
    )
    return (
      <div className="wizard-review">
        <div className="kv"><span>Campaign</span><b>{f.name || '—'}</b></div>
        <div className="kv"><span>Product</span><b>{f.product || '—'}</b></div>
        <div className="kv"><span>Audience</span><b>{[f.titles, f.industries].filter(Boolean).join(' · ') || 'any'}</b></div>
        <div className="kv"><span>Voice</span><b>{f.tone} · ≤{f.max_words} words</b></div>
        <div className="kv"><span>Guardrails</span><b>{f.daily_cap > 0 ? `${f.daily_cap}/day` : 'no cap'} · {String(f.start_hour).padStart(2, '0')}:00–{String(f.end_hour).padStart(2, '0')}:00{f.weekdays_only ? ' · weekdays' : ''}</b></div>
        <div className="kv"><span>Sending</span><b>{f.sequence_id && f.mailbox_id ? 'Apollo connected' : 'not connected yet'}</b></div>
        <p className="muted" style={{ marginTop: 16 }}>
          Next: upload a CSV of leads, run the pipeline, then review every draft with its sources before anything sends.
        </p>
      </div>
    )
  }

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
          {step > 0 && <button className="btn" onClick={() => setStep(step - 1)}>Back</button>}
          <span style={{ flex: 1 }} />
          {step < STEPS.length - 1
            ? <button className="btn primary" disabled={!stepValid()} onClick={() => setStep(step + 1)}>Continue</button>
            : <button className="btn primary" disabled={busy} onClick={create}>
                {busy ? <><span className="spinner" /> Creating…</> : 'Create campaign'}
              </button>}
        </div>
      </motion.div>
    </motion.div>
  )
}
