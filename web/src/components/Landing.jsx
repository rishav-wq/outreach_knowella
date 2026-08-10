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

// Hero signature: WIRED PROOF.
//
// The draft on the left, its evidence on the right, and a dashed line actually
// drawn between each claim and the source it came from. The colour carries the
// pairing — violet claim to violet source, teal claim to teal source — so the
// link is legible before a word is read. That is the product in one picture:
// nothing in the sentence exists without something on the right holding it up.
//
// Connectors are measured from the live DOM rather than hardcoded, because the
// claim spans wrap differently at every width and a guessed curve would point at
// nothing the moment the text reflowed.
const PAIRS = [
  { n: 1, tone: 'violet', kind: 'Press', where: 'meridianlogistics.com/news',
    quote: '“…our second Dayton hub is now operational.”', when: '11 days ago' },
  { n: 2, tone: 'teal', kind: 'Hiring', where: 'Apollo · 2 open roles',
    quote: '“Operations Coordinator” ×2, posted this month', when: '4 days ago' },
]

function WiredProof({ reduce }) {
  const wrap = useRef(null)
  const claims = useRef({})
  const cards = useRef({})
  const [paths, setPaths] = useState([])
  const [hot, setHot] = useState(null)     // the pair under the cursor, if any

  useLayoutEffect(() => {
    const draw = () => {
      const box = wrap.current?.getBoundingClientRect()
      if (!box) return
      const next = []
      for (const p of PAIRS) {
        const a = claims.current[p.n]?.getBoundingClientRect()
        const b = cards.current[p.n]?.getBoundingClientRect()
        if (!a || !b || b.left < a.right) continue      // stacked: no line to draw
        const x1 = a.right - box.left
        const y1 = a.top + a.height / 2 - box.top
        const x2 = b.left - box.left
        const y2 = b.top + Math.min(34, b.height / 2) - box.top
        const dx = Math.max(40, (x2 - x1) * 0.55)
        next.push({ ...p, d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}` })
      }
      setPaths(next)
    }
    draw()
    const ro = new ResizeObserver(draw)
    if (wrap.current) ro.observe(wrap.current)
    window.addEventListener('resize', draw)
    return () => { ro.disconnect(); window.removeEventListener('resize', draw) }
  }, [])

  return (
    <div className="wired" ref={wrap}>
      <svg className="wired-links" aria-hidden="true">
        {paths.map((p, i) => (
          <motion.path key={p.n} d={p.d}
            className={`wired-link t-${p.tone} ${hot && hot !== p.n ? 'is-dim' : ''} ${hot === p.n ? 'is-hot' : ''}`}
            initial={reduce ? false : { pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ delay: reduce ? 0 : 0.9 + i * 0.35, duration: 0.7, ease: EASE }} />
        ))}
      </svg>

      <motion.div className="wired-draft"
        initial={reduce ? false : { opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55, ease: EASE }}>
        <div className="wired-k">Draft · Meridian Logistics</div>
        <div className="wired-subj">Your new Dayton hub</div>
        <p className="wired-body">
          Hi Maria — saw Meridian{' '}
          <span className={`mark m-violet ${hot === 2 ? 'is-dim' : ''}`}
            ref={(el) => { claims.current[1] = el }}
            onMouseEnter={() => setHot(1)} onMouseLeave={() => setHot(null)}>
            opened a second distribution hub in Dayton
          </span>{' '}and that you&apos;re{' '}
          <span className={`mark m-teal ${hot === 1 ? 'is-dim' : ''}`}
            ref={(el) => { claims.current[2] = el }}
            onMouseEnter={() => setHot(2)} onMouseLeave={() => setHot(null)}>
            hiring two operations coordinators
          </span>. Usually that means the paperwork volume jumped before the headcount did.
        </p>
        <div className="wired-actions">
          <button className="btn wired-approve" type="button">Approve &amp; queue</button>
          <button className="btn" type="button">Edit</button>
          <span className="wired-note">sends from you · follows up until they reply</span>
        </div>
      </motion.div>

      <div className="wired-sources">
        {PAIRS.map((p, i) => (
          <motion.div key={p.n}
            className={`wired-src t-${p.tone} ${hot === p.n ? 'is-hot' : ''} ${hot && hot !== p.n ? 'is-dim' : ''}`}
            ref={(el) => { cards.current[p.n] = el }}
            onMouseEnter={() => setHot(p.n)} onMouseLeave={() => setHot(null)}
            initial={reduce ? false : { opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }}
            transition={{ delay: reduce ? 0 : 1.05 + i * 0.35, duration: 0.5, ease: EASE }}>
            <div className="wired-src-k">
              Source {p.n} · {p.kind}<span className="wired-when">{p.when}</span>
            </div>
            <div className="wired-where">{p.where}</div>
            <div className="wired-quote">{p.quote}</div>
          </motion.div>
        ))}
        <motion.div className="wired-neg"
          initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }}
          transition={{ delay: reduce ? 0 : 1.9, duration: 0.5 }}>
          Anything we can’t source never reaches the draft.
        </motion.div>
      </div>
    </div>
  )
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
        {/* Headline across the top, the proof beneath it — the layout the mockup
            settled on. The evidence sits to the right of the draft with a line
            drawn between each claim and its source, so the page argues by showing
            the wiring rather than describing it. */}
        <div className="lp-hero-panel">
          <motion.div className="lp-hero-head"
            {...(reduce ? {} : { initial: { opacity: 0, y: 16 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.5, ease: EASE } })}>
            <div className="lp-eyebrow-hero">Research → Draft → Your approval</div>
            <h1>The proof travels with the sentence.</h1>
          </motion.div>

          <WiredProof reduce={reduce} />

          <motion.div className="lp-cta lp-cta-hero"
            {...(reduce ? {} : { initial: { opacity: 0, y: 12 }, animate: { opacity: 1, y: 0 }, transition: { delay: 1.6, duration: 0.5, ease: EASE } })}>
            <button className="btn primary lg" onClick={onLaunch}>Open dashboard</button>
            <a className="btn lg" href="#how">See how it works →</a>
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
