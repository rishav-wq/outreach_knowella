import { useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import * as api from './api'
import Icon from './components/Icon'
import Logo from './components/Logo'
import Dashboard from './components/Dashboard'
import Review from './components/Review'
import Leads from './components/Leads'
import LeadsLibrary from './components/LeadsLibrary'
import Inbox from './components/Inbox'
import Settings from './components/Settings'
import NewCampaign from './components/NewCampaign'
import { UserMenu } from './auth'
import { pageTransition } from './components/anim'

// The nav IS the campaign lifecycle — a real sequence, so it's numbered like one:
// see where things stand → fill the list → sign off drafts → work the replies.
// Settings sits outside the sequence (operational, not lifecycle) — unnumbered.
const NAV = [
  { id: 'Overview', slug: 'overview', icon: 'dashboard', step: '01' },
  { id: 'Leads', slug: 'leads', icon: 'users', step: '02' },
  { id: 'Review', slug: 'review', icon: 'check', step: '03' },
  { id: 'Inbox', slug: 'inbox', icon: 'inbox', step: '04' },
  // Library + Settings sit outside the per-campaign lifecycle — cross-campaign / operational, unnumbered.
  { id: 'Library', slug: 'library', icon: 'list' },
  { id: 'Settings', slug: 'settings', icon: 'gear' },
]
const slugToId = (slug) => (NAV.find((n) => n.slug === slug) || NAV[0]).id
const idToSlug = (id) => (NAV.find((n) => n.id === id) || NAV[0]).slug
const tabFromHash = () => slugToId((window.location.hash.split('/')[2] || '').toLowerCase())

export default function App({ onHome }) {
  const [campaigns, setCampaigns] = useState(null) // null = still loading
  const [campaign, setCampaign] = useState('')
  const [tab, setTabState] = useState(tabFromHash)
  const [status, setStatus] = useState({})         // counts + guardrails: feeds nav counts + register
  const [sendFrom, setSendFrom] = useState('')     // which mailbox this campaign sends from
  const [error, setError] = useState('')
  const [wizard, setWizard] = useState(false)
  const reduce = useReducedMotion()
  const counts = status.counts || {}
  const queued = counts.queued || 0

  // Tab lives in the URL (#/app/<slug>) so refresh and back/forward keep your place.
  const setTab = (id) => { window.location.hash = `#/app/${idToSlug(id)}`; setTabState(id) }
  useEffect(() => {
    const onHash = () => setTabState(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    api.getCampaigns()
      .then((cs) => {
        setCampaigns(cs)
        setCampaign(cs.includes('mycampaign') ? 'mycampaign' : cs[0] || '')
      })
      .catch(() => setError('Cannot reach the backend. Start it with `uvicorn src.api:app` and reload this page.'))
  }, [])

  useEffect(() => {
    if (!campaign) return
    api.getStatus(campaign).then(setStatus).catch(() => {})
  }, [campaign, tab])
  useEffect(() => {
    if (!campaign) return
    setSendFrom('')
    api.getMailboxes(campaign).then((d) => {
      const cur = (d.mailboxes || []).find((b) => b.id === d.current)
      setSendFrom(cur ? cur.email : '')
    }).catch(() => {})
  }, [campaign])

  const body = () => {
    if (error) return <div className="banner error">{error}</div>
    if (campaigns === null) return null
    if (!campaign) return <p className="muted">No campaigns yet. Click <b>New campaign</b> to create your first one.</p>
    if (tab === 'Overview') return <Dashboard campaign={campaign} onNavigate={setTab} />
    if (tab === 'Leads') return <Leads campaign={campaign} onNavigate={setTab} />
    if (tab === 'Review') return <Review campaign={campaign} />
    if (tab === 'Inbox') return <Inbox campaign={campaign} />
    if (tab === 'Library') return <LeadsLibrary />
    if (tab === 'Settings') return <Settings campaign={campaign} />
    return null
  }

  return (
    <div className="layout">
      {/* full-width header, the product's anatomy: logo in the bar, sidebar below */}
      <header className="topbar">
        {/* single-line brand, like the product's header wordmark — everything in
            the bar shares one optical line */}
        <button className="brand" onClick={onHome} title="Back to home">
          <span className="logo"><Logo /></span>
          <span className="brand-name">Knowella</span>
          <span className="brand-sub">Outreach</span>
        </button>
        <div className="page-title">{tab}</div>
        {/* the instrument register: live send state, always in view */}
        {campaign && (
          <div className="register">
            {sendFrom && <span className="reg-item" title="This campaign sends from">{sendFrom}</span>}
            {status.guardrails && (
              <span className="reg-item" title="Sent today / daily cap">
                sent {status.guardrails.sent_today ?? 0}/{status.guardrails.daily_cap || '∞'}
              </span>
            )}
            {status.apollo_rate?.worst && (
              <span className={`reg-item ${status.apollo_rate.worst.left < 50 ? 'reg-low' : ''}`}
                title={'Apollo API budget this hour, per endpoint (from Apollo’s own response headers):\n'
                  + Object.entries(status.apollo_rate.endpoints)
                      .map(([p, e]) => `${p}: ${e.hourly_left ?? '—'} left${e.hourly_limit ? `/${e.hourly_limit}` : ''}`)
                      .join('\n')}>
                apollo {status.apollo_rate.worst.left}{status.apollo_rate.worst.limit ? `/${status.apollo_rate.worst.limit}` : ''} left/hr
              </span>
            )}
            {queued > 0 && (
              <button className="reg-item reg-link" onClick={() => setTab('Review')} title="Drafts waiting for your sign-off">
                {queued} to review
              </button>
            )}
            <span className={`dot ${status.sendable ? 'd-ok' : 'd-held'}`} title={status.sendable ? 'Sending enabled' : 'Sending not wired'} />
          </div>
        )}
        <span className="topbar-user"><UserMenu /></span>
      </header>

      <div className="shell">
      <aside className="sidebar">
        <div className="side-campaign">
          <label htmlFor="campaign-select">Campaign</label>
          {campaigns?.length > 0 && (
            <div className="side-campaign-row">
              <select id="campaign-select" value={campaign} onChange={(e) => setCampaign(e.target.value)}>
                {campaigns.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <button className="icon-btn side-edit" title="Edit this campaign — same form as creation"
                onClick={() => setWizard('edit')}>
                <Icon name="dots" size={16} />
              </button>
            </div>
          )}
          <button className="side-new" onClick={() => setWizard('new')}>
            <Icon name="plus" size={14} /> New campaign
          </button>
        </div>

        <nav className="nav">
          {NAV.map((n) => {
            // live register per lifecycle stage: what's waiting at each step
            const total = Object.values(counts).reduce((a, b) => a + b, 0)
            const navCount = n.id === 'Review' ? queued : n.id === 'Leads' ? total : 0
            return (
              <button key={n.id} className={`nav-item ${n.id === tab ? 'active' : ''} ${n.step ? '' : 'nav-op'}`} onClick={() => setTab(n.id)}>
                {n.id === tab && (
                  <motion.span layoutId="navpill" className="nav-pill" transition={{ type: 'spring', stiffness: 420, damping: 34 }} />
                )}
                {n.step ? <span className="nav-step">{n.step}</span> : <Icon name={n.icon} size={15} />}
                <span>{n.id}</span>
                {navCount > 0 && <span className={`nav-count ${n.id === 'Review' ? 'hot' : ''}`}>{navCount}</span>}
              </button>
            )
          })}
        </nav>

        <div className="sidebar-foot">
          <div className="foot-status">
            <span className={`dot ${error ? 'd-error' : 'd-ok'}`} />
            {error ? 'backend offline' : campaign || 'no campaign'}
          </div>
        </div>
      </aside>

      <div className="main">
        <div className="content">
          <AnimatePresence mode="wait">
            <motion.div key={tab + campaign} {...(reduce ? {} : pageTransition)}>
              {body()}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
      </div>{/* /shell */}

      <AnimatePresence>
        {wizard && (
          <NewCampaign
            edit={wizard === 'edit' ? campaign : undefined}
            onClose={() => setWizard(false)}
            onDeleted={(slug) => {
              setWizard(false)
              // drop it from the list and select another campaign
              setCampaigns((cs) => {
                const rest = (cs || []).filter((c) => c !== slug)
                setCampaign(rest[0] || '')
                return rest
              })
              api.getCampaigns().then(setCampaigns).catch(() => {})
              setTab('Overview')
            }}
            onCreated={(slug) => {
              const wasEdit = wizard === 'edit'
              setWizard(false)
              // refetch (a rename removes the old slug); optimistic add meanwhile
              setCampaigns((cs) => [...new Set([...(cs || []), slug])].sort())
              api.getCampaigns().then(setCampaigns).catch(() => {})
              setCampaign(slug)
              if (!wasEdit) setTab('Leads')   // edits keep you where you are
            }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
