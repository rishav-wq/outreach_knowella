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

// Hero signature: THE PINWHEEL PIPELINE. The four petals of the logo become the
// lifecycle itself — green (lead in), indigo (the AI researches + drafts),
// yellow (you approve), teal (sent) — and one lead card travels the line,
// changing state at every petal. Pure CSS timeline (16s loop) so it runs
// forever at zero cost; the non-animated default IS the final state, which is
// exactly what prefers-reduced-motion and small screens show.
function PipelineHero() {
  return (
    <div className="pipe" role="img"
      aria-label="A lead travels the pipeline: pulled in, researched and drafted by the AI with quote-verified claims, approved by you, then sent with automatic follow-ups.">
      <div className="pipe-card" aria-hidden="true">
        <div className="pl pl1">
          <div className="pl-top"><span className="pl-av">MC</span><div><b>Maria Chen</b><span>VP Operations · Meridian Logistics</span></div></div>
          <div className="pl-foot"><span className="pl-chip green">new lead</span><span>pulled from Apollo</span></div>
        </div>
        <div className="pl pl2">
          <div className="pl-fact"><i>[1]</i> opened a second Dayton hub <em>✓</em></div>
          <div className="pl-fact"><i>[2]</i> hiring 2 ops coordinators <em>✓</em></div>
          <div className="pl-foot"><span className="pl-chip indigo">draft written</span><span>every claim sourced</span></div>
        </div>
        <div className="pl pl3">
          <div className="pl-subj">Your new Dayton hub</div>
          <div className="pl-body">Hi Maria — saw that Meridian opened a second distribution hub…</div>
          <span className="pl-stamp">approved</span>
        </div>
        <div className="pl pl4">
          <div className="pl-sent"><em>✓</em> Sent</div>
          <div className="pl-foot"><span className="pl-chip teal">via your mailbox</span><span>follow-ups armed · exits on reply</span></div>
        </div>
      </div>
      <div className="pipe-track" aria-hidden="true">
        <i className="pipe-line" /><i className="pipe-fill" />
        <span className="pnode n1" /><span className="pnode n2" /><span className="pnode n3" /><span className="pnode n4" />
      </div>
      <div className="pipe-labels" aria-hidden="true">
        <div><b>Lead pulled</b><span>Apollo · CSV · LinkedIn</span></div>
        <div><b>AI researches &amp; drafts</b><span>claims quote-verified</span></div>
        <div><b>You approve</b><span>nothing sends without you</span></div>
        <div><b>Sent</b><span>follow-ups until reply</span></div>
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
        <div className="lp-hero-panel">
          <motion.div {...(reduce ? {} : { initial: { opacity: 0, y: 16 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.5, ease: EASE } })} className="lp-hero-text">
            <div className="lp-eyebrow-hero">Every claim traced to a real source</div>
            <h1>Cold outreach that&apos;s researched, <span className="hl">not&nbsp;guessed</span>.</h1>
            <p>Every lead researched against real sources. Every claim quote-verified. Every send approved by you — then followed up automatically until they reply.</p>
          </motion.div>

          <PipelineHero />

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
