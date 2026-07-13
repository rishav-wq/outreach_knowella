import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'

// Simple, filter-driven campaign creation: name your offer (pre-filled with
// Knowella's — you always sell the same thing), pick your Apollo audience
// filters from clickable options, choose a mailbox, then Create pulls the
// matching leads from Apollo.
// Pass `edit="<slug>"` and the SAME dialog opens pre-filled as the campaign
// editor (name locked, Save instead of Create, no auto-pull unless chosen).
const STEPS = ['Offer', 'Audience', 'Send']
const lines = (s) => s.split('\n').map((x) => x.trim()).filter(Boolean)

import ChipSelect, { SearchSelect, SchoolSelect, TITLE_PRESETS, INDUSTRY_PRESETS, LOCATION_PRESETS, EXCLUDE_PRESETS, SIZE_RANGES, SIZE_MAP, SENIORITY_LEVELS, SENIORITY_MAP, HIRING_PRESETS, EXCLUDE_TITLE_PRESETS, CODE_PRESETS, codesFromChips, chipsFromCodes, LABEL_BY_RANGE, LABEL_BY_SENIORITY, sizesFromLegacy, rangeFromLabel, labelFromRange } from './ChipSelect'

// The audience filters exactly as the backend stores them — built in ONE place so
// the live match-count preview and the saved campaign can never disagree.
const targeting = (f) => {
  const { naics, sic } = codesFromChips(f.codes)
  return {
    icp: { titles: f.titles, industries: f.industries, company_size: f.sizes.join(', '), geographies: f.geographies },
    apollo: {
      keywords: f.industries, exclude_keywords: f.exclude,
      employee_ranges: f.sizes.map((l) => SIZE_MAP[l] || rangeFromLabel(l)).filter(Boolean),
      seniorities: f.seniorities.map((l) => SENIORITY_MAP[l]).filter(Boolean),
      exclude_titles: f.exclude_titles,
      email_status: f.verified_only ? ['verified', 'likely to engage'] : [],
      hiring_job_titles: f.hiring_titles,
      naics_codes: naics, sic_codes: sic,
      // seeds are added from the Leads page ("More like this"); carried through
      // here so saving the wizard never wipes them, and the live count includes them
      lookalike_seeds: f.lookalike_seeds,
      schools: f.schools,
    },
  }
}

// Sequence shape exactly as the backend stores it: step 1 = first touch (always
// immediate), later steps = follow-ups with their day gaps and optional templates.
const sequenceOf = (f) => ({
  steps: f.seq_steps.map((s, i) => ({
    wait_days: i === 0 ? 0 : Math.max(1, Number(s.wait_days) || 3),
    template: s.template || '',
  })),
})

export default function NewCampaign({ onClose, onCreated, edit }) {
  const isEdit = !!edit
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
    titles: [], industries: [], geographies: ['United States'], sizes: [], exclude: [], codes: [], lookalike_seeds: [], schools: [],
    seniorities: ['Director', 'VP', 'C-suite', 'Head', 'Owner'],   // decision-makers by default
    verified_only: true,
    exclude_titles: [], hiring_titles: [], pull_limit: 25,
    // Send — seq_steps[0] is the first email; entries after it are follow-ups
    sequence_id: '', mailbox_id: '', daily_cap: 50, control_pct: 20,
    seq_steps: [{ wait_days: 0, template: '' }, { wait_days: 3, template: '' }, { wait_days: 4, template: '' }],
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

  // Live audience size: the same total_entries Apollo's own People search shows
  // for these filters, so the count can be verified against their UI. Searching
  // is free — only revealing contacts costs credits. Debounced per keystroke;
  // the stale flag drops out-of-order responses from rapid filter changes.
  const [match, setMatch] = useState({ status: 'idle', total: null })
  const targetKey = JSON.stringify(targeting(f))
  useEffect(() => {
    if (step !== 1) return
    let stale = false
    setMatch((m) => ({ status: 'loading', total: m.total }))
    const t = setTimeout(() => {
      const { icp, apollo } = JSON.parse(targetKey)
      api.previewApollo(icp, apollo)
        .then((d) => { if (!stale) setMatch({ status: 'ok', total: d.total }) })
        .catch(() => { if (!stale) setMatch({ status: 'err', total: null }) })
    }, 500)
    return () => { stale = true; clearTimeout(t) }
  }, [step, targetKey])

  // Edit mode: pre-fill the form from the campaign's saved config.
  useEffect(() => {
    if (!isEdit) return
    api.getCampaignConfig(edit).then((cfg) => {
      const icp = cfg.icp || {}, ap = cfg.apollo || {}, offer = cfg.offer || {}
      const voice = cfg.voice || {}, verify = cfg.verify || {}, send = cfg.sending || {}
      setF((p) => ({
        ...p,
        name: cfg.name || edit,
        product: offer.product || '', one_liner: offer.one_liner || '',
        value_props: (offer.value_props || []).join('\n'),
        call_to_action: offer.call_to_action || '', link: offer.link || '',
        knowledge: (cfg.knowledge || []).join('\n'),
        titles: icp.titles || [], industries: icp.industries || [],
        geographies: icp.geographies || [],
        sizes: (ap.employee_ranges || []).length
          ? (ap.employee_ranges || []).map((r) => LABEL_BY_RANGE[r] || labelFromRange(r))
          : sizesFromLegacy(icp.company_size),
        exclude: ap.exclude_keywords || [],
        codes: chipsFromCodes(ap.naics_codes || [], ap.sic_codes || []),
        lookalike_seeds: ap.lookalike_seeds || [],
        schools: ap.schools || [],
        seniorities: (ap.seniorities || []).map((v) => LABEL_BY_SENIORITY[v] || v),
        verified_only: (ap.email_status || []).length > 0,
        exclude_titles: ap.exclude_titles || [], hiring_titles: ap.hiring_job_titles || [],
        pull_limit: 0,   // editing shouldn't spend credits unless explicitly chosen
        sequence_id: send.sequence_id || '', mailbox_id: send.mailbox_id || '',
        daily_cap: send.daily_cap ?? 50,
        seq_steps: ((cfg.sequence || {}).steps || []).length
          ? cfg.sequence.steps.map((s, i) => ({ wait_days: i === 0 ? 0 : (Number(s.wait_days) || 3), template: s.template || '' }))
          : p.seq_steps,
        control_pct: (cfg.experiment || {}).enabled === false ? 0
          : Math.round(((cfg.experiment || {}).control_ratio ?? 0.2) * 100),
        tone: voice.tone || p.tone, max_words: voice.max_words || 75,
        rules: (voice.rules || []).join('\n') || p.rules,
        block_risky: !!verify.block_risky, require_deliverable: !!verify.require_deliverable,
        max_facts: (cfg.research || {}).max_facts || 12,
      }))
    }).catch(() => setError('Could not load this campaign’s settings.'))
  }, [isEdit, edit])

  const stepValid = () => (step !== 0 ? true : f.name.trim() && f.product.trim())

  const create = async () => {
    setBusy(true); setError(''); setStatus(isEdit ? 'Saving changes…' : 'Creating campaign…')
    const payload = {
      ...targeting(f),
      sequence: sequenceOf(f),
      offer: { product: f.product, one_liner: f.one_liner, value_props: lines(f.value_props), call_to_action: f.call_to_action, link: f.link },
      knowledge: lines(f.knowledge),
      voice: { tone: f.tone, max_words: Number(f.max_words) || 75, rules: lines(f.rules) },
      research: { max_facts: Number(f.max_facts) || 12 },
      experiment: { enabled: Number(f.control_pct) > 0, control_ratio: Number(f.control_pct) / 100 },
      verify: { block_risky: f.block_risky, require_deliverable: f.require_deliverable },
    }
    try {
      let slug = edit
      // renamed? migrate the config file + every lead record first
      if (isEdit) {
        const wanted = f.name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
        if (wanted && wanted !== edit) {
          setStatus('Renaming campaign…')
          const rr = await api.renameCampaign(edit, f.name)
          slug = rr.renamed
        }
      }
      // "＋ create new sequence": build a ready 3-step sequence in Apollo first
      let sequenceId = f.sequence_id
      if (sequenceId === '__new__') {
        setStatus('Creating the Apollo sequence…')
        const seq = await api.createSequence(f.name,
          f.seq_steps.slice(1).map((s) => Math.max(1, Number(s.wait_days) || 3)))
        sequenceId = seq.id
      }
      if (isEdit) {
        // sending merges server-side, so platform/field ids in the config are preserved
        await api.updateCampaign(slug, {
          ...payload,
          sending: { sequence_id: sequenceId, mailbox_id: f.mailbox_id, daily_cap: Number(f.daily_cap) || 0 },
        })
      } else {
        // No send window — sends any time; the daily cap is the only throttle.
        const r = await api.createCampaign({
          name: f.name, ...payload,
          sending: {
            platform: 'apollo', sequence_id: sequenceId, mailbox_id: f.mailbox_id,
            subject_field: 'email_subject', body_field: 'email_body', daily_cap: Number(f.daily_cap) || 0,
          },
        })
        slug = r.created
      }
      const n = Number(f.pull_limit)
      if (n > 0) {
        setStatus(`Pulling ${n} leads from Apollo…`)
        try { await api.pullApollo(slug, n) } catch { /* campaign saved; leads can be pulled later */ }
      }
      onCreated(slug)
    } catch (e) {
      setError(!isEdit && (String(e.message || e).includes('409') || /exists/.test(String(e.message)))
        ? 'A campaign with this name already exists. Pick a different name.'
        : `Could not ${isEdit ? 'save' : 'create'} the campaign: ${e.message || e}`)
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
        {field('Campaign name *', input('name', { placeholder: 'ehs-manufacturing-q3', autoFocus: !isEdit }), isEdit ? 'Renaming moves the campaign’s leads and config to the new name on save.' : 'Lowercase letters, numbers, and dashes.')}
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
        {field('Job titles', <SearchSelect presets={TITLE_PRESETS} value={f.titles} onChange={(v) => setKey('titles', v)} placeholder="Search titles, or type any + Enter" />, 'The roles you’re targeting — any title works, suggestions are shortcuts.')}
        {field('Seniority', <ChipSelect presets={SENIORITY_LEVELS.map(([l]) => l)} value={f.seniorities} onChange={(v) => setKey('seniorities', v)} allowCustom={false} />, 'Keeps the list to decision-makers — cuts juniors and assistants.')}
        {field('Industries / keywords', <SearchSelect presets={INDUSTRY_PRESETS} value={f.industries} onChange={(v) => setKey('industries', v)} placeholder="Search industries, or type any + Enter" />, 'Used to find companies in Apollo. Broad words (e.g. “manufacturing”) can match companies that merely mention them — keep it specific.')}
        {field('Industry codes (NAICS / SIC)', <SearchSelect presets={CODE_PRESETS} value={f.codes} onChange={(v) => setKey('codes', v)} placeholder="Search codes, or type any code + Enter" />, 'Official industry classifications — far more precise than keywords. Plain numbers are NAICS; prefix with “SIC” for SIC (e.g. SIC 4213). A short code covers everything under it: 484 = all trucking.')}
        {field('Company size', <ChipSelect presets={SIZE_RANGES.map(([l]) => l)} value={f.sizes} onChange={(v) => setKey('sizes', v)}
          placeholder="Custom range, e.g. 3-10 or 3000+, then Enter"
          normalize={(t) => { const r = rangeFromLabel(t); return r ? labelFromRange(r) : null }} />,
          'Employees. Pick ranges or type your own to slice finer than the presets — e.g. 3-10 skips the 1-2-person solo shops. Size strongly predicts reply rate.')}
        {field('Locations', <SearchSelect presets={LOCATION_PRESETS} value={f.geographies} onChange={(v) => setKey('geographies', v)} placeholder="Search, or type a state/city + Enter" />, 'Company HQ. Countries, or type a state/city (e.g. Texas, Chicago).')}
        {field('Universities (alumni)', <SchoolSelect value={f.schools} onChange={(v) => setKey('schools', v)} />, 'Only people who attended these schools — perfect for alma-mater outreach (a shared school is a proven warm opener). Pick the exact school from the matches; multiple schools widen the pool (alumni of any of them).')}
        {check('verified_only', 'Only pull leads with verified email addresses (recommended — fewer bounces, fewer wasted credits)')}
        {disclosure(showTarget, setShowTarget, 'Advanced targeting (optional)')}
        {showTarget && (
          <>
            {field('Actively hiring for roles', <SearchSelect presets={HIRING_PRESETS} value={f.hiring_titles} onChange={(v) => setKey('hiring_titles', v)} placeholder="Search roles, or type any + Enter" />, 'Only companies with open job postings for these roles — a strong “they have this pain right now” signal.')}
            {field('Exclude job titles', <SearchSelect presets={EXCLUDE_TITLE_PRESETS} value={f.exclude_titles} onChange={(v) => setKey('exclude_titles', v)} />, 'People with these words in their title are skipped.')}
            {field('Exclude company keywords', <SearchSelect presets={EXCLUDE_PRESETS} value={f.exclude} onChange={(v) => setKey('exclude', v)} />, 'Companies matching these are skipped — matches company names too, so a competitor or customer name here keeps their whole company out.')}
            {field('Lookalike seeds', f.lookalike_seeds.length
              ? <div className="chip-row">
                  {f.lookalike_seeds.map((s) => (
                    <button key={s.id} type="button" className="chip on custom"
                      onClick={() => setKey('lookalike_seeds', f.lookalike_seeds.filter((x) => x.id !== s.id))}>
                      {s.label || s.id} <Icon name="x" size={11} />
                    </button>
                  ))}
                </div>
              : <div className="field-hint" style={{ marginTop: 0 }}>None yet — on the Leads page, click “More like this” on a lead that worked.</div>,
              f.lookalike_seeds.length
                ? 'Apollo also finds people similar to these leads (same kind of role at the same kind of company), combined with the filters above. Click a seed to remove it.'
                : null)}
          </>
        )}
        <div className="match-row" aria-live="polite">
          {match.status === 'err'
            ? <span className="muted">Live match count unavailable — check the Apollo API key in Settings.</span>
            : <>
                <span className={`match-num ${match.status === 'loading' ? 'dim' : ''}`}>
                  {match.total == null ? '…' : match.total.toLocaleString()}
                </span>
                <span>people match these filters{match.status === 'loading' && match.total != null ? ' · updating…' : ''}</span>
              </>}
        </div>
        <div className="field-hint" style={{ marginTop: -14, marginBottom: 18 }}>
          Live from Apollo and free to check — the same total a People search with these filters shows in Apollo itself, so you can verify it there. Only revealing contacts costs credits.
        </div>
        {field('How many leads to pull now',
          <select className="field-input" value={f.pull_limit} onChange={set('pull_limit')}>
            <option value={25}>25 leads</option>
            <option value={50}>50 leads</option>
            <option value={100}>100 leads</option>
            <option value={250}>250 leads</option>
            <option value={500}>500 leads</option>
            <option value={1000}>1000 leads</option>
            <option value={0}>Don’t pull yet</option>
          </select>,
          'Pulls a batch of the matches above; each revealed lead costs ~1 Apollo credit. Start small — repeat pulls skip contacts you already have, so you can always pull the next batch later.')}
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
        {field('Emails in the sequence', (
          <div>
            <select className="field-input" style={{ maxWidth: 130 }} value={f.seq_steps.length}
              onChange={(e) => {
                const n = Number(e.target.value)
                const next = f.seq_steps.slice(0, n)
                while (next.length < n) next.push({ wait_days: next.length ? 3 : 0, template: '' })
                setKey('seq_steps', next)
              }}>
              {[1, 2, 3, 4, 5, 6, 7].map((n) => <option key={n} value={n}>{n} {n === 1 ? 'email' : 'emails'}</option>)}
            </select>
            {f.seq_steps.map((s, i) => (
              <div key={i} className="seq-step">
                <div className="seq-step-head">
                  <b>Email {i + 1}</b>
                  {i === 0
                    ? <span className="muted">first touch — sends as soon as the lead enters the sequence</span>
                    : <span className="muted">sends
                        <input className="seq-days" type="number" min={1} max={30} value={s.wait_days}
                          onChange={(e) => setKey('seq_steps', f.seq_steps.map((x, j) => j === i ? { ...x, wait_days: e.target.value } : x))} />
                        days after email {i} (only if still no reply)</span>}
                </div>
                <textarea className="field-input" rows={3} value={s.template}
                  placeholder={i === 0
                    ? 'Template (optional). Paste an email you like — the AI mirrors its structure and voice, filling it with each lead’s researched facts. Empty = the default researched first touch.'
                    : (i === 1
                      ? 'Template (optional). Empty = a short, polite bump with one fresh value line.'
                      : 'Template (optional). Empty = a new angle from a different researched fact.')}
                  onChange={(e) => setKey('seq_steps', f.seq_steps.map((x, j) => j === i ? { ...x, template: e.target.value } : x))} />
              </div>
            ))}
          </div>
        ), 'One email per step — anyone who replies stops getting the rest. Templates steer structure and voice; facts always come from each lead’s own research. Follow-ups generate 42% of replies, 4-7 touches is the sweet spot.')}
        {field('Apollo sequence', sequences.length
          ? <select className="field-input" value={f.sequence_id} onChange={set('sequence_id')}>
              <option value="">Set later</option>
              <option value="__new__">＋ Create a new {f.seq_steps.length}-email sequence from the plan above (named after this campaign)</option>
              {sequences.map((s) => <option key={s.id} value={s.id}>{s.name}{s.archived ? ' (archived)' : ''}</option>)}
            </select>
          : input('sequence_id', { placeholder: 'leave empty to set later' }),
          `Where approved leads are added. “＋ Create” builds it in Apollo to match your ${f.seq_steps.length}-email plan above (stop-on-reply, per-campaign stats) — you flip its Activate toggle in Apollo once before the first send. An existing sequence only sends as many steps as it was created with, so prefer “＋ Create” when the plan changes.`)}
        {field('Daily send cap', input('daily_cap', { type: 'number', min: 0 }), '0 = unlimited. Sends any time of day — the cap is the only throttle.')}
        {field('A/B experiment — control share', (
          <div className="slider-row">
            <input type="range" min={0} max={50} step={5} value={f.control_pct}
              onChange={(e) => setKey('control_pct', Number(e.target.value))} />
            <span className="slider-val">{Number(f.control_pct) === 0 ? 'off' : `${f.control_pct}%`}</span>
          </div>
        ), Number(f.control_pct) === 0
          ? 'Every email uses the lead’s researched facts — but you’ll never learn whether that lifts replies.'
          : `About 1 in ${Math.max(2, Math.round(100 / Number(f.control_pct)))} emails goes out as a plain (no researched facts) control, so the campaign measures whether fact-led openers earn more replies.`)}
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
  const createLabel = isEdit
    ? (Number(f.pull_limit) > 0 ? `Save & pull ${f.pull_limit}` : 'Save changes')
    : (Number(f.pull_limit) > 0 ? `Create & pull ${f.pull_limit}` : 'Create campaign')

  return (
    <motion.div className="modal-scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      <motion.div className="wizard" role="dialog" aria-label="New campaign" onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: 24, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 12 }}
        transition={{ type: 'spring', stiffness: 380, damping: 34 }}>
        <div className="wizard-head">
          <div className="wizard-title">{isEdit ? `Edit campaign · ${edit}` : 'New campaign'}</div>
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
