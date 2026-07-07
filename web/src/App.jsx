import { useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import * as api from './api'
import Icon from './components/Icon'
import Dashboard from './components/Dashboard'
import Review from './components/Review'
import Leads from './components/Leads'
import Inbox from './components/Inbox'
import Settings from './components/Settings'
import NewCampaign from './components/NewCampaign'
import { UserMenu } from './auth'
import { pageTransition } from './components/anim'

// Lifecycle order: see the campaign → fill it → review drafts → engage → configure.
const NAV = [
  { id: 'Overview', slug: 'overview', icon: 'dashboard' },
  { id: 'Leads', slug: 'leads', icon: 'users' },
  { id: 'Review', slug: 'review', icon: 'check' },
  { id: 'Inbox', slug: 'inbox', icon: 'inbox' },
  { id: 'Settings', slug: 'settings', icon: 'gear' },
]
const slugToId = (slug) => (NAV.find((n) => n.slug === slug) || NAV[0]).id
const idToSlug = (id) => (NAV.find((n) => n.id === id) || NAV[0]).slug
const tabFromHash = () => slugToId((window.location.hash.split('/')[2] || '').toLowerCase())

export default function App({ onHome }) {
  const [campaigns, setCampaigns] = useState(null) // null = still loading
  const [campaign, setCampaign] = useState('')
  const [tab, setTabState] = useState(tabFromHash)
  const [queued, setQueued] = useState(0)
  const [error, setError] = useState('')
  const [wizard, setWizard] = useState(false)
  const reduce = useReducedMotion()

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
    api.getStatus(campaign).then((s) => setQueued(s.counts?.queued || 0)).catch(() => {})
  }, [campaign, tab])

  const body = () => {
    if (error) return <div className="banner error">{error}</div>
    if (campaigns === null) return null
    if (!campaign) return <p className="muted">No campaigns yet. Click <b>New campaign</b> to create your first one.</p>
    if (tab === 'Overview') return <Dashboard campaign={campaign} onNavigate={setTab} />
    if (tab === 'Leads') return <Leads campaign={campaign} onNavigate={setTab} />
    if (tab === 'Review') return <Review campaign={campaign} />
    if (tab === 'Inbox') return <Inbox campaign={campaign} />
    if (tab === 'Settings') return <Settings campaign={campaign} />
    return null
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <button className="brand" onClick={onHome} title="Back to home">
          <span className="logo">K</span>
          <div>
            <div className="brand-name">Knowella</div>
            <div className="brand-sub">Outreach</div>
          </div>
        </button>

        <div className="side-campaign">
          <label htmlFor="campaign-select">Campaign</label>
          {campaigns?.length > 0 && (
            <select id="campaign-select" value={campaign} onChange={(e) => setCampaign(e.target.value)}>
              {campaigns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
          <button className="side-new" onClick={() => setWizard(true)}>
            <Icon name="plus" size={14} /> New campaign
          </button>
        </div>

        <nav className="nav">
          {NAV.map((n) => (
            <button key={n.id} className={`nav-item ${n.id === tab ? 'active' : ''}`} onClick={() => setTab(n.id)}>
              {n.id === tab && (
                <motion.span layoutId="navpill" className="nav-pill" transition={{ type: 'spring', stiffness: 420, damping: 34 }} />
              )}
              <Icon name={n.icon} size={17} /> <span>{n.id}</span>
              {n.id === 'Review' && queued > 0 && <span className="nav-count">{queued}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="foot-status">
            <span className={`dot ${error ? 'd-error' : 'd-ok'}`} />
            {error ? 'backend offline' : campaign || 'no campaign'}
          </div>
          <UserMenu />
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="page-title">{tab}</div>
        </header>
        <div className="content">
          <AnimatePresence mode="wait">
            <motion.div key={tab + campaign} {...(reduce ? {} : pageTransition)}>
              {body()}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      <AnimatePresence>
        {wizard && (
          <NewCampaign
            onClose={() => setWizard(false)}
            onCreated={(slug) => {
              setWizard(false)
              setCampaigns((cs) => [...new Set([...(cs || []), slug])].sort())
              setCampaign(slug)
              setTab('Leads')
            }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
