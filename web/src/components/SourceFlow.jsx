import { motion } from 'framer-motion'

// Sources on the left, campaigns on the right, and the leads waiting between them.
// The whole point is the middle: a source is only interesting because of what it
// feeds, and a campaign is only ready because something is queued for it. Drawing
// the two columns separately would hide the only number that matters — how many
// leads are sitting here right now, and where they're headed.
//
// Routes are scored against what each campaign already declares it wants, and the
// matched terms ride along on every item. An unrouted lead is shown as unrouted,
// never quietly filed into whichever campaign sorted first.

const NODE_H = 76
const GAP = 12
const GUTTER = 132

export default function SourceFlow({ data, selected, onSelect }) {
  const sources = data.sources || []
  const campaigns = data.campaigns || []
  const flows = data.flows || []
  const rows = Math.max(sources.length, campaigns.length, 1)
  const H = rows * (NODE_H + GAP) - GAP
  const yOf = (i) => i * (NODE_H + GAP) + NODE_H / 2

  const srcIdx = Object.fromEntries(sources.map((s, i) => [s.id, i]))
  const campIdx = Object.fromEntries(campaigns.map((c, i) => [c.name, i]))
  const totalReady = campaigns.reduce((a, c) => a + c.ready, 0)
  const maxFlow = Math.max(1, ...flows.map((f) => f.items.length))

  const key = (f) => `${f.source_id}|${f.campaign}`

  return (
    <div className="flow">
      <div className="flow-head">
        <div>
          <div className="map-stat">{totalReady}</div>
          <div className="map-stat-k">{totalReady === 1 ? 'lead ready to add' : 'leads ready to add'}</div>
        </div>
        <div>
          <div className="map-stat">{sources.length}</div>
          <div className="map-stat-k">{sources.length === 1 ? 'source feeding' : 'sources feeding'}</div>
        </div>
        {selected && <button className="btn map-clear" onClick={() => onSelect('')}>Show all</button>}
      </div>

      <div className="flow-board" style={{ minHeight: H }}>
        <div className="flow-col">
          {sources.map((s, i) => (
            <motion.div key={s.id} className="flow-node" style={{ height: NODE_H }}
              initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.05 }}>
              <div className="flow-node-k">{s.type || 'source'}</div>
              <div className="flow-node-n">{s.name}</div>
              <div className="flow-node-v">{s.ready} ready<span className="muted"> · {s.leads} total leads</span></div>
            </motion.div>
          ))}
        </div>

        <svg className="flow-links" viewBox={`0 0 ${GUTTER} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          {flows.map((f) => {
            const y1 = yOf(srcIdx[f.source_id] ?? 0)
            const y2 = yOf(campIdx[f.campaign] ?? 0)
            const on = !selected || selected === key(f)
            // Stroke width carries the volume, so a fat line means a busy route
            // without needing to read the label.
            const wgt = 2 + 7 * (f.items.length / maxFlow)
            return (
              <motion.path key={key(f)} className={`flow-link ${f.campaign ? '' : 'unrouted'} ${on ? '' : 'dim'}`}
                d={`M0,${y1} C${GUTTER * 0.5},${y1} ${GUTTER * 0.5},${y2} ${GUTTER},${y2}`}
                strokeWidth={wgt} fill="none"
                initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.5 }}
                onClick={() => onSelect(selected === key(f) ? '' : key(f))} />
            )
          })}
        </svg>

        <div className="flow-col">
          {campaigns.map((c, i) => (
            <motion.div key={c.name || '_unrouted'}
              className={`flow-node flow-node-c ${c.name ? '' : 'is-unrouted'}`} style={{ height: NODE_H }}
              initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.05 }}>
              <div className="flow-node-k">{c.name ? 'campaign' : 'no campaign matched'}</div>
              <div className="flow-node-n">{c.name || 'Needs a campaign'}</div>
              <div className="flow-node-v">{c.ready} ready</div>
            </motion.div>
          ))}
        </div>
      </div>

      <div className="flow-legend">
        {flows.map((f) => (
          <button key={key(f)} className={`flow-chip ${selected === key(f) ? 'on' : ''} ${f.campaign ? '' : 'unrouted'}`}
            onClick={() => onSelect(selected === key(f) ? '' : key(f))}>
            {f.source} <span>→</span> {f.campaign || 'unrouted'} <b>{f.items.length}</b>
          </button>
        ))}
      </div>
    </div>
  )
}
