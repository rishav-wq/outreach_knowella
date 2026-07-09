import { motion, useReducedMotion } from 'framer-motion'
import Icon from './Icon'

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

// Signature: a draft that verifies itself on load — each claim highlights, its
// source tag stamps on, and the header resolves to "quote-verified".
function VerifyReceipt() {
  const reduce = useReducedMotion()
  const on = (from) => (reduce ? false : from)
  const claim = (delay) => ({
    initial: on({ backgroundColor: 'rgba(231,246,240,0)' }),
    animate: { backgroundColor: 'rgba(231,246,240,1)' },
    transition: { delay, duration: 0.45, ease: EASE },
  })
  const stamp = (delay) => ({
    initial: on({ opacity: 0, scale: 0.5, rotate: -8 }),
    animate: { opacity: 1, scale: 1, rotate: 0 },
    transition: { delay, type: 'spring', stiffness: 520, damping: 17 },
  })
  return (
    <div className="receipt in-window">
      {!reduce && (
        <motion.div className="receipt-scan"
          initial={{ y: '-100%', opacity: 0.9 }} animate={{ y: '400%', opacity: 0 }}
          transition={{ delay: 0.8, duration: 1.5, ease: 'easeInOut' }} />
      )}
      <div className="receipt-head">
        <b>Draft · Meridian Foods</b>
        <span className="receipt-status">
          <motion.span className="rs-working" initial={on({ opacity: 1 })} animate={{ opacity: 0 }} transition={{ delay: 2.4, duration: 0.3 }}>
            verifying<span className="rs-dots">…</span>
          </motion.span>
          <motion.span className="rs-done" initial={on({ opacity: 0 })} animate={{ opacity: 1 }} transition={{ delay: 2.6, duration: 0.3 }}>
            <Icon name="check" size={12} /> quote-verified
          </motion.span>
        </span>
      </div>
      <div className="receipt-body">
        <div className="receipt-subject">Your Dayton plant&apos;s recordables</div>
        <p style={{ margin: 0 }}>
          Hi Maria — saw that Meridian{' '}
          <span className="ev2">
            <motion.mark {...claim(1.0)}>closed out its OSHA citation from the March inspection</motion.mark>
            <motion.span className="ev-tag" {...stamp(1.4)}>osha</motion.span>
          </span>{' '}
          and is{' '}
          <span className="ev2">
            <motion.mark {...claim(1.6)}>hiring two EHS coordinators in Dayton</motion.mark>
            <motion.span className="ev-tag" {...stamp(2.0)}>hiring</motion.span>
          </span>.
          Teams doing that shift usually hit a wall tracking corrective actions in spreadsheets —
          that&apos;s the exact gap Knowella closes…
        </p>
      </div>
      <div className="receipt-foot">
        <motion.span className="facts" initial={on({ opacity: 0 })} animate={{ opacity: 1 }} transition={{ delay: 2.6, duration: 0.4 }}>
          7 facts · 3 sources
        </motion.span>
        <div className="actions">
          <span className="btn">Edit</span>
          <span className="btn approve"><Icon name="check" size={13} /> Approve</span>
        </div>
      </div>
    </div>
  )
}

// The hero centerpiece: the product itself, framed as a floating app window —
// mini lifecycle sidebar, the self-verifying draft, and the evidence rail.
function AppWindow() {
  const reduce = useReducedMotion()
  return (
    <motion.div className="lp-window"
      initial={reduce ? false : { opacity: 0, y: 26 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15, duration: 0.6, ease: EASE }}>
      <div className="lpw-chrome"><span /><span /><span /><em>knowella outreach — review</em></div>
      <div className="lpw-grid">
        <div className="lpw-side">
          <div className="lpw-brand"><span className="logo">K</span></div>
          {[['01', 'Overview'], ['02', 'Leads'], ['03', 'Review'], ['04', 'Inbox']].map(([n, t]) => (
            <div key={n} className={`lpw-nav ${t === 'Review' ? 'on' : ''}`}><i>{n}</i>{t}</div>
          ))}
        </div>
        <VerifyReceipt />
        <div className="lpw-ev">
          <div className="lpw-ev-label">Grounded in 7 verified facts</div>
          <div className="ev-card"><div className="ev-claim">Closed out OSHA citation from the March inspection at the Dayton plant.</div><div className="ev-meta"><span className="src">osha</span></div></div>
          <div className="ev-card"><div className="ev-claim">Hiring two EHS coordinators in Dayton, posted 11 days ago.</div><div className="ev-meta"><span className="src">hiring</span></div></div>
        </div>
      </div>
    </motion.div>
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
          <div className="lp-logo"><span className="logo">K</span> Knowella <span className="muted">Outreach</span></div>
          <div className="lp-links">
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <a href="#proof">Customers</a>
          </div>
          <button className="btn primary" onClick={onLaunch}>Open dashboard</button>
        </div>
      </nav>

      {/* centered hero: claim → sub → CTAs, then the product itself as the centerpiece */}
      <header className="lp-hero">
        <div className="lp-hero-glow" aria-hidden="true" />
        <motion.div {...(reduce ? {} : { initial: { opacity: 0, y: 16 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.5, ease: EASE } })} className="lp-hero-text">
          <div className="lp-pill"><span className="lp-pill-dot" /> Outreach for EHS &amp; safety teams</div>
          <h1>Cold outreach that&apos;s <span className="hl">researched, not&nbsp;guessed</span>.</h1>
          <p>Every lead researched against real sources. Every claim quote-verified. Every send approved by you — then followed up automatically until they reply.</p>
          <div className="lp-cta">
            <button className="btn primary lg" onClick={onLaunch}>Open dashboard</button>
            <a className="btn lg" href="#how">See how it works</a>
          </div>
        </motion.div>

        <AppWindow />

        <motion.div {...fade} className="lp-metrics">
          <div><b>12+</b><span>verified facts per lead</span></div>
          <div><b>3</b><span>touches per lead, auto-sent</span></div>
          <div><b>100%</b><span>human-approved sends</span></div>
          <div><b>0</b><span>made-up claims</span></div>
        </motion.div>
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
              <p>Every lead-specific claim is quote-verified against a real source — OSHA records, hiring posts, their own site, the news. If it can&apos;t be proven, it never gets written.</p>
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
                <div className="ldm-row"><i>To</i><b>Jerry Knight · Safety Director</b></div>
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
            <div className="lp-logo"><span className="logo">K</span> Knowella <span className="muted">Outreach</span></div>
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
