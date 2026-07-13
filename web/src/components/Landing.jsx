import { useLayoutEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import Icon from './Icon'
import Logo from './Logo'

const EASE = [0.22, 1, 0.36, 1]

const STEPS = [
  { n: '01', t: 'Pull your leads', d: 'Pull straight from Apollo by your ICP — seniority, size, hiring signals, verified emails — or import any CSV.' },
  { n: '02', t: 'Research & draft', d: 'Every lead is researched across the web and their own site, then written into a grounded, specific email — each claim tied to its source.' },
  { n: '03', t: 'Review & send', d: 'Read every draft beside its evidence. Approve the ones worth sending; the 3-touch sequence goes out through your own mailboxes.' },
]
const QUOTES = [
  { q: 'Staying on top of inspections, training, and safety records is much easier now. Everything’s organized in one place, and it saves us a lot of time.', r: 'Director of Safety', c: 'Food Manufacturing Company' },
  { q: 'Knowella made it easy to digitize our hazard tracking, audits, and training records — saving time and strengthening compliance across our operations.', r: 'Supply Chain Manager', c: 'Food Distribution Company' },
]

// The two cited claims: highlighted phrase in the draft, footnote number, and
// the margin note (source card) it traces to. One place, so mark/note/line agree.
const CLAIMS = [
  {
    text: 'opened a second distribution hub in Dayton last month',
    tag: 'news',
    quote: '“Meridian Logistics opens second Dayton distribution hub.”',
    meta: 'local news · last month',
  },
  {
    text: 'hiring two operations coordinators there',
    tag: 'hiring',
    quote: '“Operations Coordinator (2 openings) — Dayton, OH.”',
    meta: 'careers page · 11 days ago',
  },
]

// Hero signature: the TRACE. A draft whose claims carry footnote markers, with
// each source docked as a margin note and a hairline leader line drawn from
// claim to note — the page doing literally what the eyebrow says. Lines are
// measured from the real DOM (so they survive resize/font-load) and drawn with
// a pathLength animation; hovering a claim lights its source and vice versa.
function TracedDraft() {
  const reduce = useReducedMotion()
  const on = (from) => (reduce ? false : from)
  const wrap = useRef(null)
  const markRefs = [useRef(null), useRef(null)]
  const noteRefs = [useRef(null), useRef(null)]
  const [paths, setPaths] = useState([])
  const [hot, setHot] = useState(0)   // 0 = none, 1/2 = linked pair highlighted

  useLayoutEffect(() => {
    const el = wrap.current
    if (!el) return
    const measure = () => {
      const c = el.getBoundingClientRect()
      setPaths(markRefs.map((m, i) => {
        const a = m.current?.getBoundingClientRect()
        const b = noteRefs[i].current?.getBoundingClientRect()
        if (!a || !b) return null
        // note 1 sits LEFT of the draft, note 2 RIGHT — line runs note-edge to claim-edge
        const left = i === 0
        if (left ? a.left <= b.right : b.left <= a.right) return null   // stacked layout: no lines
        const x1 = (left ? b.right : b.left) - c.left + (left ? 3 : -3)
        const y1 = b.top + 20 - c.top
        const x2 = (left ? a.left : a.right) - c.left + (left ? -3 : 3)
        const y2 = a.top + a.height / 2 - c.top
        const mx = (x1 + x2) / 2
        return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`
      }))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    if (document.fonts?.ready) document.fonts.ready.then(measure).catch(() => {})
    return () => ro.disconnect()
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // load sequence: claim sweeps → line draws → note lands, one trace at a time
  const T = (i) => ({ claim: 0.9 + i * 0.9, line: 1.15 + i * 0.9, note: 1.3 + i * 0.9 })
  const link = (i) => ({
    onMouseEnter: () => setHot(i + 1), onMouseLeave: () => setHot(0),
  })

  const claimSpan = (i) => (
    <span className="ev2" {...link(i)}>
      <motion.mark ref={markRefs[i]} className={hot === i + 1 ? 'on' : ''}
        initial={on({ backgroundSize: '0% 100%' })} animate={{ backgroundSize: '100% 100%' }}
        transition={{ delay: T(i).claim, duration: 0.5, ease: EASE }}>
        {CLAIMS[i].text}
      </motion.mark>
      <sup className="fn">{i + 1}</sup>
    </span>
  )

  return (
    <motion.div className="trace" ref={wrap}
      initial={on({ opacity: 0, y: 26 })} animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15, duration: 0.6, ease: EASE }}>
      <div className="trace-side left">{note(0)}</div>
      <div className="receipt">
        <div className="receipt-head">
          <b>Draft · Meridian Logistics</b>
          <span className="receipt-status">
            <motion.span className="rs-working" initial={on({ opacity: 1 })} animate={{ opacity: 0 }} transition={{ delay: 3.1, duration: 0.3 }}>
              verifying<span className="rs-dots">…</span>
            </motion.span>
            <motion.span className="rs-done" initial={on({ opacity: 0 })} animate={{ opacity: 1 }} transition={{ delay: 3.2, duration: 0.3 }}>
              <Icon name="check" size={12} /> quote-verified
            </motion.span>
          </span>
        </div>
        <div className="receipt-body">
          <div className="receipt-subject">Your new Dayton hub</div>
          <p style={{ margin: 0 }}>
            Hi Maria — saw that Meridian {claimSpan(0)} and is {claimSpan(1)}.
            Standing up a second site usually means processes split across spreadsheets —
            that&apos;s the exact gap we close…
          </p>
        </div>
        <div className="receipt-foot">
          <motion.span className="facts" initial={on({ opacity: 0 })} animate={{ opacity: 1 }} transition={{ delay: 3.2, duration: 0.4 }}>
            7 facts · 3 sources
          </motion.span>
          <div className="actions">
            <span className="btn">Edit</span>
            <span className="btn approve"><Icon name="check" size={13} /> Approve</span>
          </div>
        </div>
      </div>

      <div className="trace-side right">{note(1)}</div>
      <svg className="trace-svg" aria-hidden="true">
        {paths.map((d, i) => (d &&
          <motion.path key={i} d={d} className={hot === i + 1 ? 'on' : ''}
            initial={on({ pathLength: 0 })} animate={{ pathLength: 1 }}
            transition={{ delay: T(i).line, duration: 0.45, ease: EASE }} />
        ))}
      </svg>
    </motion.div>
  )

  function note(i) {
    const cl = CLAIMS[i]
    // entrance animates an outer wrapper so the note's CSS tilt + hover lift
    // (inline transforms would clash with framer's) stay on the card itself
    return (
      <motion.div key={cl.tag}
        initial={on({ opacity: 0, x: i === 0 ? -10 : 10 })} animate={{ opacity: 1, x: 0 }}
        transition={{ delay: T(i).note, duration: 0.4, ease: EASE }}>
        <div ref={noteRefs[i]} {...link(i)} className={`trace-note ${hot === i + 1 ? 'on' : ''}`}>
          <div className="tn-head">
            <i>[{i + 1}]</i> {cl.tag}
            <motion.span className="tn-stamp"
              initial={on({ opacity: 0, scale: 0.5, rotate: -10 })} animate={{ opacity: 1, scale: 1, rotate: -3 }}
              transition={{ delay: T(i).note + 0.15, type: 'spring', stiffness: 520, damping: 17 }}>
              verified
            </motion.span>
          </div>
          <div className="tn-quote">{cl.quote}</div>
          <div className="tn-meta">{cl.meta}</div>
        </div>
      </motion.div>
    )
  }
}

export default function Landing({ onLaunch }) {
  const reduce = useReducedMotion()
  const fade = reduce ? {} : {
    initial: { opacity: 0, y: 18 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, margin: '-70px' },
    transition: { duration: 0.5, ease: EASE },
  }
  return (
    <div className="lp">
      <nav className="lp-nav">
        <div className="lp-nav-inner">
          <div className="lp-logo"><span className="logo"><Logo /></span> Knowella <span className="muted">Outreach</span></div>
          <div className="lp-links">
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <a href="#proof">Customers</a>
          </div>
          <button className="btn primary" onClick={onLaunch}>Open dashboard</button>
        </div>
      </nav>

      {/* hero: one contained panel in Knowella's login gradient — copy left,
          the live product window right, metrics as a frosted strip along the bottom */}
      <header className="lp-hero">
        <div className="lp-hero-panel">
          <motion.div {...(reduce ? {} : { initial: { opacity: 0, y: 16 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.5, ease: EASE } })} className="lp-hero-text">
            <div className="lp-eyebrow-hero">Every claim traced to a real source</div>
            <h1>Cold outreach that&apos;s researched, <span className="hl">not&nbsp;guessed</span>.</h1>
            <p>Every lead researched against real sources. Every claim quote-verified. Every send approved by you — then followed up automatically until they reply.</p>
          </motion.div>

          <TracedDraft />

          <motion.div {...(reduce ? {} : { initial: { opacity: 0, y: 12 }, animate: { opacity: 1, y: 0 }, transition: { delay: 0.45, duration: 0.5, ease: EASE } })} className="lp-cta lp-cta-hero">
            <button className="btn primary lg" onClick={onLaunch}>Open dashboard</button>
            <a className="btn lg" href="#how">See how it works →</a>
          </motion.div>

          <motion.div {...fade} className="lp-metrics">
            <div><b>12+</b><span>verified facts per lead</span></div>
            <div><b>3</b><span>touches per lead, auto-sent</span></div>
            <div><b>100%</b><span>human-approved sends</span></div>
            <div><b>0</b><span>made-up claims</span></div>
          </motion.div>
        </div>
      </header>

      <section className="lp-section" id="how">
        <div className="lp-inner">
          <motion.div {...fade} className="lp-head">
            <div className="lp-eyebrow">How it works</div>
            <h2>From a raw list to a sent, personalized sequence — in three steps.</h2>
          </motion.div>
          <div className="lp-steps">
            {STEPS.map((s, i) => (
              <motion.div {...fade} transition={{ ...fade.transition, delay: i * 0.08 }} className="lp-step" key={s.t}>
                <div className="lp-step-num">{s.n}</div>
                <h3>{s.t}</h3><p>{s.d}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* alternating feature rows, each with a small live-styled product crop */}
      <section className="lp-section alt" id="features">
        <div className="lp-inner">
          <motion.div {...fade} className="lp-head">
            <div className="lp-eyebrow">Why it&apos;s different</div>
            <h2>Personalization you can actually trust.</h2>
          </motion.div>

          <motion.div {...fade} className="lp-row">
            <div className="lp-row-text">
              <h3>Grounded, never guessed</h3>
              <p>Every lead-specific claim is quote-verified against a real source — hiring posts, the news, public records, their own site. If it can&apos;t be proven, it never gets written.</p>
              <ul>
                <li>Exact supporting quote stored with every fact</li>
                <li>Stale and boilerplate facts filtered out</li>
                <li>Sources one click away in review</li>
              </ul>
            </div>
            <div className="lp-row-art">
              <div className="ev-card"><div className="ev-claim">Currently hiring a Specialized Heavy Haul Driver.</div><div className="ev-quote">“Barber Trucking, Inc. is seeking to hire a Specialized Heavy Haul Driver…”</div><div className="ev-meta"><span className="src">careers</span></div></div>
              <div className="ev-card"><div className="ev-claim">Main terminal at 3661 Route 28 N, Brookville, PA.</div><div className="ev-meta"><span className="src">homepage</span></div></div>
            </div>
          </motion.div>

          <motion.div {...fade} className="lp-row rev">
            <div className="lp-row-text">
              <h3>You sign off every send</h3>
              <p>Drafts wait in a review queue with their evidence beside them. Edit by hand, or tell the AI what to change — nothing leaves without your approval.</p>
              <ul>
                <li>Keyboard-speed queue: approve, reject, revise</li>
                <li>Day-3 and day-7 follow-ups drafted with each email</li>
                <li>Anyone who replies exits the sequence automatically</li>
              </ul>
            </div>
            <div className="lp-row-art">
              <div className="lp-doc-mock">
                <div className="ldm-row"><i>To</i><b>Jerry Knight · Operations Director</b></div>
                <div className="ldm-row"><i>Subject</i><b>Berner&apos;s new Dover facility</b></div>
                <div className="ldm-body">Saw Berner Trucking moved into a larger complex to accommodate growth…</div>
                <div className="ldm-actions"><span className="btn">Revise</span><span className="btn approve"><Icon name="check" size={12} /> Approve</span></div>
              </div>
            </div>
          </motion.div>

          <motion.div {...fade} className="lp-row">
            <div className="lp-row-text">
              <h3>Replies, understood</h3>
              <p>Every answer is classified the moment it lands — interested, not interested, out of office, or opt-out. Opt-outs go straight to the do-not-contact list; the numbers that matter roll up on your overview.</p>
              <ul>
                <li>Positive-reply rate and meetings booked, not vanity opens</li>
                <li>Built-in A/B: do researched openers out-convert?</li>
                <li>Bounce and domain health watched for you</li>
              </ul>
            </div>
            <div className="lp-row-art">
              <div className="lp-inbox-mock">
                <div className="lim-row"><b>Sue Brown</b><span className="badge s-approved">interested</span></div>
                <div className="lim-row"><b>Rob McFarland</b><span className="badge s-drafted">not interested</span></div>
                <div className="lim-row"><b>Paul Hansen</b><span className="badge s-held">out of office</span></div>
                <div className="lim-row"><b>Dan Fauvell</b><span className="badge s-invalid">opted out</span></div>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      <section className="lp-section" id="proof">
        <div className="lp-inner">
          <motion.div {...fade} className="lp-head">
            <div className="lp-eyebrow">Trusted by teams</div>
            <h2>What Knowella customers say.</h2>
          </motion.div>
          <div className="lp-quotes">
            {QUOTES.map((t) => (
              <motion.div {...fade} className="lp-quote" key={t.r}>
                <p>“{t.q}”</p>
                <div className="lp-quote-by"><strong>{t.r}</strong><span>{t.c}</span></div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-band">
        <div className="lp-band-stripe" aria-hidden="true" />
        <motion.div {...fade} className="lp-inner">
          <h2>Ready to run your first campaign?</h2>
          <p>Pull a list, let the pipeline research and write, then review and send — all in one place.</p>
          <button className="btn primary lg" onClick={onLaunch}>Open dashboard</button>
        </motion.div>
      </section>

      <footer className="lp-footer">
        <div className="lp-inner lp-foot">
          <div className="lp-foot-brand">
            <div className="lp-logo"><span className="logo"><Logo /></span> Knowella <span className="muted">Outreach</span></div>
            <p>Grounded cold outreach that researches every lead and never makes things up.</p>
          </div>
          <div className="lp-foot-cols">
            <div><h4>Product</h4><a href="#how">How it works</a><a href="#features">Features</a><button className="linklike" onClick={onLaunch}>Open dashboard</button></div>
            <div><h4>Company</h4><a href="https://knowella.com" target="_blank" rel="noreferrer">Knowella</a><a href="https://knowella.com" target="_blank" rel="noreferrer">About</a></div>
            <div><h4>Resources</h4><a href="#proof">Customers</a><a href="https://knowella.com" target="_blank" rel="noreferrer">Contact</a></div>
          </div>
        </div>
        <div className="lp-inner lp-copy">© 2026 Knowella · Outreach</div>
      </footer>
    </div>
  )
}
