import { useEffect, useState } from 'react'
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

// Hero signature: THE SOURCED EMAIL.
//
// The old hero diagrammed the process — four dots, four labels, a card that
// changed state. Every outreach tool on the internet has that. But the thing
// nobody else can put on a page is the ARTEFACT: a cold email whose every factual
// claim carries a footnote, and a sources block underneath where each one resolves
// to a quote. That is the whole product, and showing it argues better than any
// adjective. It also speaks the customer's own language — safety directors live in
// citations, standard references and audit trails.
//
// Claim and evidence are linked: hover a marker and its source lifts. Left alone,
// it cycles slowly so the connection is visible without anyone touching anything.
// Teal is the check colour because in this design system teal means verified;
// nothing here is decorative.
const CLAIMS = [
  {
    n: 1,
    text: 'opened a second distribution hub in Dayton',
    src: 'meridianlogistics.com/news',
    quote: '“…our second Dayton hub is now operational.”',
    when: '11 days ago',
  },
  {
    n: 2,
    text: 'hiring two operations coordinators',
    src: 'Apollo · 2 open roles',
    quote: '“Operations Coordinator” ×2, posted this month',
    when: '4 days ago',
  },
]

function SourcedEmail({ reduce }) {
  const [live, setLive] = useState(1)
  const [held, setHeld] = useState(null)
  useEffect(() => {
    if (reduce) return
    const t = setInterval(() => setLive((n) => (n === 1 ? 2 : 1)), 3200)
    return () => clearInterval(t)
  }, [reduce])
  const on = held ?? live

  const rise = (delay) => (reduce ? {} : {
    initial: { opacity: 0, y: 10 },
    animate: { opacity: 1, y: 0 },
    transition: { delay, duration: 0.5, ease: EASE },
  })

  return (
    <motion.div className="src-doc" {...(reduce ? {} : {
      initial: { opacity: 0, y: 22 }, animate: { opacity: 1, y: 0 },
      transition: { duration: 0.6, ease: EASE },
    })}
      role="img"
      aria-label="A cold email in which every factual claim carries a numbered footnote, with a sources block beneath showing the quote each one came from, and an approved stamp.">
      <div className="src-bar" aria-hidden="true">
        <span className="src-to">To</span> maria@meridianlogistics.com
        <span className="src-tag">draft</span>
      </div>

      <div className="src-body" aria-hidden="true">
        <motion.div className="src-subj" {...rise(0.15)}>Your new Dayton hub</motion.div>
        <motion.p {...rise(0.25)}>
          Hi Maria — saw Meridian{' '}
          <span className={`src-claim ${on === 1 ? 'on' : ''}`}
            onMouseEnter={() => setHeld(1)} onMouseLeave={() => setHeld(null)}>
            opened a second distribution hub in Dayton<sup>1</sup>
          </span>{' '}and that you&apos;re{' '}
          <span className={`src-claim ${on === 2 ? 'on' : ''}`}
            onMouseEnter={() => setHeld(2)} onMouseLeave={() => setHeld(null)}>
            hiring two operations coordinators<sup>2</sup>
          </span>. Usually that means the paperwork volume jumped before the headcount did.
        </motion.p>
      </div>

      <motion.div className="src-foot" {...rise(0.45)} aria-hidden="true">
        <div className="src-foot-k">Sources</div>
        {CLAIMS.map((c, i) => (
          <motion.div key={c.n} className={`src-ref ${on === c.n ? 'on' : ''}`}
            onMouseEnter={() => setHeld(c.n)} onMouseLeave={() => setHeld(null)}
            {...rise(0.55 + i * 0.12)}>
            <span className="src-num">{c.n}</span>
            <div>
              <div className="src-where">{c.src}<span className="src-when">{c.when}</span></div>
              <div className="src-quote">{c.quote}</div>
            </div>
            <span className="src-tick">✓</span>
          </motion.div>
        ))}
      </motion.div>

      <motion.div className="src-stamp" aria-hidden="true"
        {...(reduce ? {} : {
          initial: { opacity: 0, scale: 0.94 }, animate: { opacity: 1, scale: 1 },
          transition: { delay: 0.95, duration: 0.45, ease: EASE },
        })}>
        <span className="src-approved">Approved by you</span>
        <span className="src-sent">sent from your mailbox · follows up until they reply</span>
      </motion.div>
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
        {/* Two columns: the argument on the left, the artefact proving it on the
            right. Centred and stacked read as a template and left the page with no
            focal point; side by side, the claim and its evidence are in the same
            glance — which is the product's whole idea. */}
        <div className="lp-hero-panel">
          <motion.div {...(reduce ? {} : { initial: { opacity: 0, y: 16 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.5, ease: EASE } })} className="lp-hero-left">
            <div className="lp-eyebrow-hero">No invented claims · nothing sends without you</div>
            <h1>Every sentence in this email <span className="hl">has a source.</span></h1>
            <p>We research each lead, cite what we find, and put the evidence beside the draft.
              You approve it. Then it sends from your own mailbox and follows up until they reply.</p>

            <div className="lp-cta lp-cta-hero">
              <button className="btn primary lg" onClick={onLaunch}>Open dashboard</button>
              <a className="btn lg" href="#how">See how it works →</a>
            </div>

            {/* The four-number strip that was here said what the email now shows.
                One quiet line instead, carrying what the artefact can't. */}
            <p className="lp-hero-note">
              Sends from your own mailboxes · Apollo, CSV or LinkedIn as the source ·
              <b> no claim reaches a draft without a source behind it</b>
            </p>
          </motion.div>

          <div className="lp-hero-right">
            <SourcedEmail reduce={reduce} />
          </div>
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
