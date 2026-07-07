import { motion, useReducedMotion } from 'framer-motion'
import Icon from './Icon'

const EASE = [0.22, 1, 0.36, 1]

const STEPS = [
  { n: '01', t: 'Pull your leads', d: 'Pull straight from Apollo by your ICP, or import any CSV. Missing domains and emails are enriched automatically, at no cost.' },
  { n: '02', t: 'Research & draft', d: 'Every lead is researched across the web and their own site, then written into a grounded, specific email — with each claim tied to its source.' },
  { n: '03', t: 'Review & send', d: 'Read every draft and its evidence on the review board. Approve the ones worth sending; they go out through your own warmed inboxes.' },
]
const FEATURES = [
  { icon: 'link', t: 'Grounded, never guessed', d: 'Every lead-specific claim is quote-verified against a real source. If it can’t be proven, it never gets written.' },
  { icon: 'board', t: 'Multi-source research', d: 'Homepage, news, hiring signals, OSHA records — the strongest, most recent facts surface first.' },
  { icon: 'inbox', t: 'You approve every send', d: 'Nothing leaves without your decision. Read, edit, approve — one lead at a time or a whole batch.' },
  { icon: 'users', t: 'Your inboxes, your reputation', d: 'Sends go through your own warmed mailboxes, so deliverability stays in your control.' },
]
const STATS = [
  { n: '12+', l: 'facts verified per lead' },
  { n: '0', l: 'made-up claims' },
  { n: '<1¢', l: 'per personalized email' },
]
const QUOTES = [
  { q: 'Staying on top of inspections, training, and safety records is much easier now. Everything’s organized in one place, and it saves us a lot of time.', r: 'Director of Safety', c: 'Food Manufacturing Company' },
  { q: 'Knowella made it easy to digitize our hazard tracking, audits, and training records — saving time and strengthening compliance across our operations.', r: 'Supply Chain Manager', c: 'Food Distribution Company' },
]

// Signature: a draft that verifies itself on load. Each lead-specific claim gets
// highlighted, then its source tag stamps on in sequence, a scan sweeps the page,
// and the header resolves from "verifying…" to "quote-verified". You watch the
// product's whole promise happen in three seconds.
function VerifyReceipt() {
  const reduce = useReducedMotion()
  const on = (from) => (reduce ? false : from) // reduced motion → render final state
  const claim = (delay) => ({
    initial: on({ backgroundColor: 'rgba(226,241,232,0)' }),
    animate: { backgroundColor: 'rgba(226,241,232,1)' },
    transition: { delay, duration: 0.45, ease: [0.22, 1, 0.36, 1] },
  })
  const stamp = (delay) => ({
    initial: on({ opacity: 0, scale: 0.5, rotate: -8 }),
    animate: { opacity: 1, scale: 1, rotate: 0 },
    transition: { delay, type: 'spring', stiffness: 520, damping: 17 },
  })

  return (
    <motion.div className="receipt"
      initial={reduce ? false : { opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-70px' }} transition={{ duration: 0.5, ease: EASE }}>
      {!reduce && (
        <motion.div className="receipt-scan"
          initial={{ y: '-100%', opacity: 0.9 }} animate={{ y: '400%', opacity: 0 }}
          transition={{ delay: 0.3, duration: 1.5, ease: 'easeInOut' }} />
      )}
      <div className="receipt-head">
        <b>Draft · Meridian Foods</b>
        <span className="receipt-status">
          <motion.span className="rs-working" initial={on({ opacity: 1 })} animate={{ opacity: 0 }} transition={{ delay: 2.0, duration: 0.3 }}>
            verifying<span className="rs-dots">…</span>
          </motion.span>
          <motion.span className="rs-done" initial={on({ opacity: 0 })} animate={{ opacity: 1 }} transition={{ delay: 2.2, duration: 0.3 }}>
            <Icon name="check" size={12} /> quote-verified
          </motion.span>
        </span>
      </div>
      <div className="receipt-body">
        <div className="receipt-subject">Your Dayton plant&apos;s recordables</div>
        <p style={{ margin: 0 }}>
          Hi Maria — saw that Meridian{' '}
          <span className="ev2">
            <motion.mark {...claim(0.6)}>closed out its OSHA citation from the March inspection</motion.mark>
            <motion.span className="ev-tag" {...stamp(1.0)}>osha</motion.span>
          </span>{' '}
          and is{' '}
          <span className="ev2">
            <motion.mark {...claim(1.2)}>hiring two EHS coordinators in Dayton</motion.mark>
            <motion.span className="ev-tag" {...stamp(1.6)}>hiring</motion.span>
          </span>.
          Teams doing that shift usually hit a wall tracking corrective actions in spreadsheets —
          that&apos;s the exact gap Knowella closes…
        </p>
      </div>
      <div className="receipt-foot">
        <motion.span className="facts" initial={on({ opacity: 0 })} animate={{ opacity: 1 }} transition={{ delay: 2.2, duration: 0.4 }}>
          7 facts · 3 sources
        </motion.span>
        <div className="actions">
          <span className="btn">Edit</span>
          <span className="btn approve"><Icon name="check" size={13} /> Approve</span>
        </div>
      </div>
    </motion.div>
  )
}

export default function Landing({ onLaunch }) {
  const reduce = useReducedMotion()
  // Scroll-reveal for real users; final state immediately under reduced motion.
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

      <header className="lp-hero">
        <div className="lp-hero-glow" aria-hidden="true" />
        <motion.div {...fade} className="lp-hero-text">
          <div className="lp-pill"><span className="lp-pill-dot" /> Outreach for EHS &amp; safety teams</div>
          <h1>Cold outreach that&apos;s <span className="hl">researched, not&nbsp;guessed</span>.</h1>
          <p>Knowella Outreach finds real signals on every lead, writes an email grounded in <em>their</em> world, and waits for your approval before a single send. No hallucinations, no generic spam.</p>
          <div className="lp-cta">
            <button className="btn primary lg" onClick={onLaunch}>Open dashboard</button>
            <a className="btn lg" href="#how">See how it works</a>
          </div>
          <div className="lp-trust">
            <span><Icon name="link" size={13} /> quote-verified</span>
            <span><Icon name="check" size={13} /> human-approved</span>
            <span><Icon name="inbox" size={13} /> your inboxes</span>
          </div>
        </motion.div>

        <VerifyReceipt />
      </header>

      <section className="lp-section" id="how">
        <div className="lp-inner">
          <motion.div {...fade} className="lp-head">
            <div className="lp-eyebrow">How it works</div>
            <h2>From a raw list to a sent, personalized email — in three steps.</h2>
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

      <section className="lp-section alt" id="features">
        <div className="lp-inner">
          <motion.div {...fade} className="lp-head">
            <div className="lp-eyebrow">Why it&apos;s different</div>
            <h2>Personalization you can actually trust.</h2>
          </motion.div>
          <div className="lp-features">
            {FEATURES.map((f) => (
              <motion.div {...fade} className="lp-feature" key={f.t}>
                <div className="lp-badge"><Icon name={f.icon} size={18} /></div>
                <div><h3>{f.t}</h3><p>{f.d}</p></div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-band-stats">
        <div className="lp-inner lp-stats">
          {STATS.map((s) => (
            <motion.div {...fade} className="lp-stat" key={s.l}>
              <div className="lp-stat-n">{s.n}</div><div className="lp-stat-l">{s.l}</div>
            </motion.div>
          ))}
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
