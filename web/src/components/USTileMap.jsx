import { motion } from 'framer-motion'

// A tile-grid map of the US: one square per state, arranged so neighbours are
// roughly where you expect them. It is deliberately schematic rather than
// geographic — a real outline gives Rhode Island four pixels and Montana a
// hundred, which is exactly backwards when the thing you're plotting is one
// citation per state. Every square is the same size, so every citation reads the
// same, and there is no map library or external asset involved.
//
// Columns run west→east, rows north→south. Dots are empty cells.
const GRID = [
  'AK  .  .  .  .  .  .  .  .  .  ME',
  ' .  .  .  .  .  .  .  .  .  VT NH',
  ' .  WA ID MT ND MN WI MI  .  NY MA',
  ' .  OR NV WY SD IA IL IN OH PA CT',
  ' .  CA UT CO NE MO KY WV VA MD RI',
  ' .  .  AZ NM KS AR TN NC SC DC DE',
  ' .  .  .  .  OK LA MS AL GA  . NJ',
  'HI  .  .  .  TX  .  .  .  FL  .  .',
].map((r) => r.trim().split(/\s+/))

const CELL = 34
const GAP = 4
const COLS = 11
const ROWS = GRID.length

export default function USTileMap({ rows, selected, onSelect, renderPopover }) {
  // rows: [{ state, penalty, company }] — one entry per citation
  const byState = {}
  let placed = 0
  for (const r of rows) {
    if (!r.state) continue
    placed++
    const b = (byState[r.state] ||= { n: 0, penalty: 0, names: [] })
    b.n += 1
    b.penalty += Number(r.penalty) || 0
    b.names.push(r.company)
  }
  const unplaced = rows.length - placed
  const maxPenalty = Math.max(1, ...Object.values(byState).map((b) => b.penalty))
  const total = Object.values(byState).reduce((a, b) => a + b.penalty, 0)

  const w = COLS * (CELL + GAP) - GAP
  const h = ROWS * (CELL + GAP) - GAP

  // Where the selected tile sits, as a percentage of the SVG box — the SVG scales
  // with the container, so percentages track it without measuring the DOM.
  let anchor = null
  for (let y = 0; y < ROWS && !anchor; y++) {
    const x = GRID[y].indexOf(selected)
    if (selected && x >= 0) {
      anchor = {
        left: `${((x * (CELL + GAP) + CELL / 2) / w) * 100}%`,
        top: `${((y * (CELL + GAP) + CELL) / h) * 100}%`,
        side: x > COLS / 2 ? 'right' : 'left',
      }
    }
  }

  return (
    <div className="map-wrap">
      <div className="map-head">
        <div>
          <div className="map-stat">{placed}</div>
          <div className="map-stat-k">
            {placed === 1 ? 'employer cited' : 'employers cited'} in {Object.keys(byState).length}{' '}
            {Object.keys(byState).length === 1 ? 'state' : 'states'}
          </div>
        </div>
        <div>
          <div className="map-stat map-stat-money">${total.toLocaleString()}</div>
          <div className="map-stat-k">in proposed penalties</div>
        </div>
        {selected && (
          <button className="btn map-clear" onClick={() => onSelect('')}>Clear {selected}</button>
        )}
      </div>

      <div className="map-scroll">
        <div className="map-stage">
        <svg viewBox={`0 0 ${w} ${h}`} className="map-svg" role="img"
          aria-label={`United States by state, ${placed} cited employers`}>
          {GRID.map((row, y) => row.map((code, x) => {
            if (code === '.') return null
            const b = byState[code]
            const on = !!b
            // Weight by penalty, not count: one $700K citation is a bigger opening
            // than three small ones, and at these volumes count alone is all 1s.
            const t = on ? 0.3 + 0.7 * (b.penalty / maxPenalty) : 0
            const dim = selected && selected !== code
            const cx = x * (CELL + GAP)
            const cy = y * (CELL + GAP)
            return (
              <motion.g key={code} className={`map-cell ${on ? 'on' : ''} ${dim ? 'dim' : ''}`}
                initial={on ? { opacity: 0, scale: 0.6 } : false}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: on ? 0.04 * (x + y) : 0, type: 'spring', stiffness: 320, damping: 22 }}
                style={{ transformOrigin: `${cx + CELL / 2}px ${cy + CELL / 2}px` }}
                onClick={() => on && onSelect(selected === code ? '' : code)}>
                <rect x={cx} y={cy} width={CELL} height={CELL} rx="6"
                  fill={on ? `rgba(253, 117, 14, ${t})` : 'var(--panel)'}
                  stroke={selected === code ? 'var(--caution)' : 'var(--line)'}
                  strokeWidth={selected === code ? 2 : 1} />
                <text x={cx + CELL / 2} y={cy + CELL / 2 + 4} textAnchor="middle"
                  className={`map-code ${on && t > 0.55 ? 'inv' : ''}`}>{code}</text>
                {on && b.n > 1 && (
                  <circle cx={cx + CELL - 4} cy={cy + 4} r="6" className="map-badge-bg" />
                )}
                {on && b.n > 1 && (
                  <text x={cx + CELL - 4} y={cy + 7.5} textAnchor="middle" className="map-badge">{b.n}</text>
                )}
                {on && <title>{`${code} — ${b.names.join(', ')} · $${b.penalty.toLocaleString()}`}</title>}
              </motion.g>
            )
          }))}
        </svg>
        {anchor && renderPopover && (
          <motion.div className={`map-pop map-pop-${anchor.side}`} style={{ left: anchor.left, top: anchor.top }}
            initial={{ opacity: 0, y: -6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ type: 'spring', stiffness: 400, damping: 28 }}>
            <span className="map-pop-arrow" />
            <button className="map-pop-x" onClick={() => onSelect('')} aria-label="Close">×</button>
            {renderPopover(selected, byState[selected])}
          </motion.div>
        )}
        </div>
      </div>

      <p className="map-note">
        Shaded by total proposed penalty. Click a state to filter the list.
        {unplaced > 0 && <> {unplaced} citation{unplaced === 1 ? '' : 's'} couldn’t be placed — the release
          gave no state.</>}
      </p>
    </div>
  )
}
