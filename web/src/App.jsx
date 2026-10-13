import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import * as api from './api'
import Icon from './components/Icon'
import Logo from './components/Logo'
import Dashboard from './components/Dashboard'
import Review from './components/Review'
import Leads from './components/Leads'
import People from './components/People'
import Companies from './components/Companies'
import Marketing from './components/Marketing'
import Sources from './components/Sources'
import Signals from './components/Signals'
import Audiences from './components/Audiences'
import Publications from './components/Publications'
import Inbox from './components/Inbox'
import Settings from './components/Settings'
import NewCampaign from './components/NewCampaign'
import Training from './components/Training'
import Team from './components/Team'
import Today from './components/Today'
import { UserMenu } from './auth'
import { MeContext, isAdmin, canSales, canMarketing } from './me'
import { pageTransition } from './components/anim'

// TWO MODES, one shell — like the product's workspace switcher. Sales is
// campaign-scoped (picker + the numbered lifecycle); Marketing is Library-scoped
// (blasts + audiences). Library & Settings are shared: the Library is the bridge
// between the engines (sales exhaust → marketing fuel → warm clicks → sales).
// What each role sees follows src/access.py: admins get both modes and the Team
// page, sales only the sales mode, marketing only the marketing mode.
const SALES_NAV = [
  { id: 'Overview', slug: 'overview', icon: 'dashboard', step: '01' },
  { id: 'Leads', slug: 'leads', icon: 'users', step: '02' },
  { id: 'Review', slug: 'review', icon: 'check', step: '03' },
  { id: 'Inbox', slug: 'inbox', icon: 'inbox', step: '04' },
]
const MKT_NAV = [
  { id: 'Blasts', slug: 'blasts', icon: 'upload' },
  { id: 'Publications', slug: 'publications', icon: 'list' },
  { id: 'Audiences', slug: 'audiences', icon: 'users' },
]
// A rep's day (tasks and targets), and everyone you sell to: one record per person and
// per company (sales and admins).
const CRM_NAV = [
  { id: 'Today', slug: 'today', icon: 'check', shared: true },
  { id: 'Library', slug: 'library', icon: 'list', shared: true },
  { id: 'Companies', slug: 'companies', icon: 'building', shared: true },
]
const SHARED_NAV = [
  { id: 'Training', slug: 'training', icon: 'board', shared: true },
  { id: 'Signals', slug: 'signals', icon: 'inbox', shared: true },
  { id: 'Sources', slug: 'sources', icon: 'download', shared: true },
  { id: 'Settings', slug: 'settings', icon: 'gear', shared: true },
  { id: 'Team', slug: 'team', icon: 'users', shared: true },
]
const NAV = [...SALES_NAV, ...MKT_NAV, ...CRM_NAV, ...SHARED_NAV]
const MKT_IDS = new Set(MKT_NAV.map((n) => n.id))
const SALES_IDS = new Set(SALES_NAV.map((n) => n.id))
const slugToId = (slug) => {
  if (slug === 'marketing') return 'Blasts'   // legacy URL from phase 1
  return (NAV.find((n) => n.slug === slug) || NAV[0]).id
}
const idToSlug = (id) => (NAV.find((n) => n.id === id) || NAV[0]).slug
const tabFromHash = () => slugToId((window.location.hash.split('?')[0].split('/')[2] || '').toLowerCase())

const allowedTab = (me, id) => {
  if (SALES_IDS.has(id) || id === 'Today' || id === 'Library' || id === 'Companies') return canSales(me)
  if (MKT_IDS.has(id)) return canMarketing(me)
  if (id === 'Team') return isAdmin(me)
  return true
}
const homeTab = (me, campaigns) => {
  if (me.role === 'marketing') return 'Blasts'
  if (me.role === 'sales') return (campaigns || []).length ? 'Today' : 'Training'   // a new BDR starts on Training
  return 'Overview'
}

export default function App({ onHome }) {
  const [me, setMe] = useState(null)               // the signed-in person, from /api/me
  const [campaigns, setCampaigns] = useState(null) // null = still loading
  const [campaign, setCampaign] = useState('')
  const [tab, setTabState] = useState(tabFromHash)
  const [mode, setMode] = useState(() => (MKT_IDS.has(tabFromHash()) ? 'marketing' : 'sales'))
  const [status, setStatus] = useState({})         // counts + guardrails: feeds nav counts + register
  const [sendFrom, setSendFrom] = useState('')     // which mailbox this campaign sends from
  const [error, setError] = useState('')
  const [dueCount, setDueCount] = useState(0)     // tasks overdue or due today, on the Today nav item
  const [wizard, setWizard] = useState(false)
  const routed = useRef(false)
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
  // mode follows the tab (shared tabs keep the current mode)
  useEffect(() => {
    if (MKT_IDS.has(tab)) setMode('marketing')
    else if (SALES_IDS.has(tab)) setMode('sales')
  }, [tab])
  const switchMode = (m) => { setMode(m); setTab(m === 'marketing' ? 'Blasts' : 'Overview') }

  useEffect(() => {
    api.getMe()
      .then((m) => {
        setMe(m)
        if (m.role === 'marketing') setMode('marketing')
        else if (m.role === 'sales') setMode('sales')
        return api.getCampaigns()
      })
      .then((cs) => {
        setCampaigns(cs)
        setCampaign(cs.includes('mycampaign') ? 'mycampaign' : cs[0] || '')
      })
      .catch((e) => setError(e.status
        ? api.errorText(e)
        : 'Cannot reach the backend. Start it with `uvicorn src.api:app` and reload this page.'))
  }, [])

  // Land on the role's home the first time (a new BDR starts on Training), and never
  // stay on a page this role can't use (an old bookmark, a typed URL).
  useEffect(() => {
    if (!me || campaigns === null) return
    if (!routed.current) {
      routed.current = true
      const fresh = tab === 'Overview' && !(campaigns || []).length
      const noPage = !(window.location.hash.split('?')[0].split('/')[2] || '')   // opened the app itself, no page named
      if (!allowedTab(me, tab) || fresh || noPage) { setTab(homeTab(me, campaigns)); return }
    }
    if (!allowedTab(me, tab)) setTab(homeTab(me, campaigns))
  }, [me, campaigns, tab])

  useEffect(() => {
    if (!campaign) return
    api.getStatus(campaign, true).then(setStatus).catch(() => {})
    // keep the header pills honest while sends run: sent count + Apollo quota move live
    // (light: the header never shows tokens, so skip that aggregation every tick)
    const t = setInterval(() => api.getStatus(campaign, true).then(setStatus).catch(() => {}), 15000)
    return () => clearInterval(t)
  }, [campaign, tab])
  useEffect(() => {
    if (!campaign) return
    setSendFrom('')
    api.getMailboxes(campaign).then((d) => {
      const cur = (d.mailboxes || []).find((b) => b.id === d.current)
      setSendFrom(cur ? cur.email : '')
    }).catch(() => {})
  }, [campaign])

  useEffect(() => {
    if (!me || !canSales(me)) return
    const count = () => {
      const day = api.localDay()
      api.listTasks({ status: 'open' }).then((d) => setDueCount((d.tasks || []).filter((t) => t.due <= day).length)).catch(() => {})
    }
    count()
    window.addEventListener(api.TASKS_CHANGED, count)
    return () => window.removeEventListener(api.TASKS_CHANGED, count)
  }, [me, tab])

  const body = () => {
    if (error) return <div className="banner error">{error}</div>
    if (!me || campaigns === null || !allowedTab(me, tab)) return null
    // pages that don't belong to a campaign
    if (tab === 'Training') return <Training onNavigate={setTab} />
    if (tab === 'Team') return <Team />
    if (tab === 'Today') return <Today />
    if (tab === 'Library') return <People onPromoted={() => campaign && api.getStatus(campaign).then(setStatus).catch(() => {})} />
    if (tab === 'Companies') return <Companies />
    if (tab === 'Blasts') return <Marketing />
    if (tab === 'Publications') return <Publications />
    if (tab === 'Audiences') return <Audiences />
    if (tab === 'Sources') return <Sources />
    if (tab === 'Signals') return <Signals />
    if (tab === 'Settings') return <Settings campaign={campaign} />
    // a campaign's own pages
    if (!campaign) {
      return (
        <div className="empty">
          <h3>No campaigns yet</h3>
          <p className="muted">Click <b>New campaign</b> to create your first one.
            {me.role === 'sales' && ' Or ask an admin to give you an existing one.'}</p>
        </div>
      )
    }
    if (tab === 'Overview') return <Dashboard campaign={campaign} onNavigate={setTab} />
    if (tab === 'Leads') return <Leads campaign={campaign} onNavigate={setTab} />
    if (tab === 'Review') return <Review campaign={campaign} />
    if (tab === 'Inbox') return <Inbox campaign={campaign} />
    return null
  }

  const both = isAdmin(me)                         // only admins switch between the two engines
  const navItems = [...(mode === 'sales' ? SALES_NAV : MKT_NAV), ...CRM_NAV, ...SHARED_NAV].filter((n) => allowedTab(me, n.id))

  return (
    <MeContext.Provider value={me}>
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
        {campaign && mode === 'sales' && (
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
        {/* the engine switcher — the product's workspace-switch pattern */}
        {both && (
          <div className="mode-seg" role="tablist" aria-label="Engine">
            <button role="tab" aria-selected={mode === 'sales'} className={mode === 'sales' ? 'on' : ''} onClick={() => switchMode('sales')}>Sales</button>
            <button role="tab" aria-selected={mode === 'marketing'} className={mode === 'marketing' ? 'on' : ''} onClick={() => switchMode('marketing')}>Marketing</button>
          </div>
        )}

        {mode === 'sales' && canSales(me) && (
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
        )}

        {me && (
        <nav className="nav">
          {navItems.map((n) => {
            // live register per lifecycle stage: what's waiting at each step
            const total = Object.values(counts).reduce((a, b) => a + b, 0)
            const navCount = n.id === 'Review' ? queued
              : n.id === 'Leads' ? total
              : n.id === 'Signals' ? (status.signals_open || 0)
              : n.id === 'Today' ? dueCount : 0
            return (
              <button key={n.id} className={`nav-item ${n.id === tab ? 'active' : ''} ${n.shared ? 'nav-op' : ''}`} onClick={() => setTab(n.id)}>
                {n.id === tab && (
                  <motion.span layoutId="navpill" className="nav-pill" transition={{ type: 'spring', stiffness: 420, damping: 34 }} />
                )}
                {n.step ? <span className="nav-step">{n.step}</span> : <Icon name={n.icon} size={15} />}
                <span>{n.id}</span>
                {navCount > 0 && <span className={`nav-count ${n.id === 'Review' || n.id === 'Today' ? 'hot' : ''}`}>{navCount}</span>}
              </button>
            )
          })}
        </nav>
        )}

        <div className="sidebar-foot">
          <div className="foot-status">
            <span className={`dot ${error ? 'd-error' : 'd-ok'}`} />
            {error ? 'backend offline' : mode === 'sales' ? (campaign || 'no campaign') : (me?.email || '')}
          </div>
        </div>
      </aside>

      <div className="main">
        <div className={`content ${tab === 'Training' && !error ? 'content-frame' : ''}`}>
          <AnimatePresence mode="wait">
            {/* campaign pages remount on a campaign switch; the rest (Training's frame
                above all) don't reload when the picker changes */}
            <motion.div key={SALES_IDS.has(tab) ? tab + campaign : tab} className="page-body" {...(reduce ? {} : pageTransition)}>
              {me && !me.admins_configured && (
                <div className="banner error">
                  No admins are set up on the server, so nobody can reach the existing campaigns or set roles.
                  Add <code>ADMIN_EMAILS</code> (comma-separated) to the server’s <code>.env</code> and restart the app.
                </div>
              )}
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
    </MeContext.Provider>
  )
}
