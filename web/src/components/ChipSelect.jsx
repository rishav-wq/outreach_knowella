import { useEffect, useRef, useState } from 'react'
import Icon from './Icon'

// Pickable presets for audience filters (click to toggle; type + Enter adds any
// custom value — Apollo's title/keyword/location filters are free-form, so you're
// never limited to these; they're just one-click shortcuts for the common picks).
export const TITLE_PRESETS = [
  'Safety Director', 'Director of Safety', 'VP of Safety', 'Safety Manager',
  'EHS Manager', 'EHS Director', 'VP of EHS', 'Health & Safety Manager', 'HSE Manager',
  'Environmental Health and Safety Manager', 'Operations Director', 'VP Operations', 'COO',
  'Fleet Manager', 'Director of Fleet', 'Fleet Safety Manager', 'Compliance Manager',
  'Director of Compliance', 'Risk Manager', 'Plant Manager', 'Warehouse Manager', 'Quality Manager',
]
export const INDUSTRY_PRESETS = [
  'Logistics', 'Trucking', 'Freight', 'Transportation', 'Warehousing', 'Supply Chain',
  'Distribution', 'Manufacturing', 'Construction', 'Building Materials', 'Oil & Energy',
  'Utilities', 'Mining & Metals', 'Food Production', 'Chemicals', 'Automotive', 'Wholesale',
]
export const LOCATION_PRESETS = ['United States', 'Canada', 'United Kingdom', 'Australia', 'Ireland', 'New Zealand']
export const EXCLUDE_PRESETS = ['computer software', 'information technology', 'staffing & recruiting', 'marketing & advertising', 'financial services', 'consulting']
// Apollo standard employee ranges: label -> "lo,hi" value
export const SIZE_RANGES = [['1-10', '1,10'], ['11-20', '11,20'], ['21-50', '21,50'], ['51-100', '51,100'], ['101-200', '101,200'], ['201-500', '201,500'], ['501-1000', '501,1000'], ['1001-2000', '1001,2000'], ['2001-5000', '2001,5000'], ['5001-10000', '5001,10000'], ['10001+', '10001,1000000']]
export const SIZE_MAP = Object.fromEntries(SIZE_RANGES)
// Apollo's 11 seniority levels: display label -> API value
export const SENIORITY_LEVELS = [['Owner', 'owner'], ['Founder', 'founder'], ['C-suite', 'c_suite'], ['Partner', 'partner'], ['VP', 'vp'], ['Head', 'head'], ['Director', 'director'], ['Manager', 'manager'], ['Senior', 'senior'], ['Entry', 'entry'], ['Intern', 'intern']]
export const SENIORITY_MAP = Object.fromEntries(SENIORITY_LEVELS)
export const HIRING_PRESETS = ['driver', 'safety manager', 'safety coordinator', 'EHS specialist', 'compliance officer', 'warehouse associate', 'mechanic']
export const EXCLUDE_TITLE_PRESETS = ['assistant', 'intern', 'student', 'consultant', 'recruiter']
export const LABEL_BY_RANGE = Object.fromEntries(SIZE_RANGES.map(([l, v]) => [v, l]))
export const LABEL_BY_SENIORITY = Object.fromEntries(SENIORITY_LEVELS.map(([l, v]) => [v, l]))

// Legacy campaigns (created via config file, pre-wizard) store size as a raw string
// like "4-20000". Map it onto the chip ranges it covers so forms show the real choice.
export const sizesFromLegacy = (companySize) => {
  const m = String(companySize || '').replace(/\s/g, '').match(/^(\d+)(?:-(\d+))?$/)
  if (!m) return []
  const lo = Number(m[1]); const hi = Number(m[2] ?? m[1])
  return SIZE_RANGES.filter(([, v]) => {
    const [rlo, rhi] = v.split(',').map(Number)
    return rhi >= lo && rlo <= hi
  }).map(([l]) => l)
}

// Toggle chips from a preset list; optionally add a custom value by typing + Enter.
export default function ChipSelect({ presets, value, onChange, placeholder, allowCustom = true }) {
  const [text, setText] = useState('')
  const toggle = (v) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])
  const addCustom = () => {
    const v = text.trim()
    if (v && !value.includes(v)) onChange([...value, v])
    setText('')
  }
  const custom = value.filter((v) => !presets.includes(v))
  return (
    <div className="chips">
      <div className="chip-row">
        {presets.map((p) => (
          <button key={p} type="button" className={`chip ${value.includes(p) ? 'on' : ''}`} onClick={() => toggle(p)}>{p}</button>
        ))}
        {custom.map((v) => (
          <button key={v} type="button" className="chip on custom" onClick={() => toggle(v)}>{v} <Icon name="x" size={11} /></button>
        ))}
      </div>
      {allowCustom && (
        <input className="field-input chip-input" value={text} placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCustom() } }} />
      )}
    </div>
  )
}


// Searchable multi-select dropdown for long option lists: type to filter the
// presets, Enter (or the add row) to add any custom value — Apollo's filters are
// free-form, so nothing is restricted to the suggestions. Selected values render
// as removable chips under the control.
export function SearchSelect({ presets, value, onChange, placeholder = 'Search or type your own…' }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef(null)
  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  const toggle = (v) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])
  const ql = q.trim().toLowerCase()
  const options = presets.filter((p) => p.toLowerCase().includes(ql))
  const canAdd = ql && ![...presets, ...value].some((x) => x.toLowerCase() === ql)
  const add = () => { if (canAdd) { onChange([...value, q.trim()]); setQ('') } }
  return (
    <div className="msel" ref={ref}>
      <button type="button" className="msel-btn" onClick={() => setOpen(!open)}>
        {value.length ? `${value.length} selected` : 'Choose…'}
        <Icon name="chevron" size={13} />
      </button>
      {open && (
        <div className="msel-menu">
          <input className="msel-search" autoFocus value={q} placeholder={placeholder}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
          {canAdd && <button type="button" className="msel-add" onClick={add}>＋ Add “{q.trim()}”</button>}
          <div className="msel-opts">
            {options.map((p) => (
              <label key={p} className="msel-opt">
                <input type="checkbox" checked={value.includes(p)} onChange={() => toggle(p)} />
                {p}
              </label>
            ))}
            {options.length === 0 && !canAdd && <div className="msel-none">Nothing matches — keep typing and press Enter to add it.</div>}
          </div>
        </div>
      )}
      {value.length > 0 && (
        <div className="chip-row" style={{ marginTop: 8 }}>
          {value.map((v) => (
            <button key={v} type="button" className="chip on custom" onClick={() => toggle(v)}>{v} <Icon name="x" size={11} /></button>
          ))}
        </div>
      )}
    </div>
  )
}
