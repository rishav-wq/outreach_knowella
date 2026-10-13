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
import { Activity, CampaignFrame, CampaignList, Sequence } from './components/Campaigns'
import { UserMenu } from './auth'
import { MeContext, isAdmin, canSales, canMarketing } from './me'
import { pageTransition } from './components/anim'

// TWO MODES, one shell — like the product's workspace switcher. Sales works in
// campaigns (a list, and each campaign a page with its own tabs); Marketing is
// Library-scoped (blasts + audiences). Library & Settings are shared: the Library is
// the bridge between the engines (sales exhaust → marketing fuel → warm clicks → sales).
// What each role sees follows src/access.py: admins get both modes and the Team
// page, sales only the sales mode, marketing only the marketing mode.
const SALES_NAV = [
  { id: 'Campaigns', slug: 'campaigns', icon: 'board' },
]
// A campaign's own tabs, at #/app/campaigns/<name>/<slug> (docs/knowcrm-requirements-audit.md
// §5.1). The ids are the pages' old names, so links between them keep working.
const CAMPAIGN_TABS = [
  { id: 'Overview', slug: 'overview', label: 'Overview' },
  { id: 'Sequence', slug: 'sequence', label: 'Sequence' },
  { id: 'Leads', slug: 'leads', label: 'Leads' },
  { id: 'Review', slug: 'review', label: 'Review' },
  { id: 'Activity', slug: 'activity', label: 'Activity' },
  { id: 'Inbox', slug: 'replies', label: 'Replies' },
]
const CAMPAIGN_IDS = new Set(CAMPAIGN_TABS.map((t) => t.id))
// Links from before campaigns had pages (#/app/leads …) open the current campaign.
const LEGACY_CAMPAIGN_SLUGS = { overview: 'Overview', leads: 'Leads', review: 'Review', inbox: 'Inbox' }
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
const SALES_IDS = new Set([...SALES_NAV.map((n) => n.id), ...CAMPAIGN_IDS])
const slugToId = (slug) => {
  if (slug === 'marketing') return 'Blasts'   // legacy URL from phase 1
  return (NAV.find((n) => n.slug === slug) || NAV[0]).id
}
const idToSlug = (id) => (NAV.find((n) => n.id === id) || NAV[0]).slug
// The page (and, for a campaign's tabs, which campaign) a URL names. campaign is null
// when the URL doesn't say (a legacy link): the current campaign is meant.
const routeFromHash = () => {
  const parts = window.location.hash.split('?')[0].split('/')
  const slug = (parts[2] || '').toLowerCase()
  if (slug === 'campaigns' && parts[3]) {
    let name = ''
    try { name = decodeURIComponent(parts[3]) } catch { name = '' }
    const sub = CAMPAIGN_TABS.find((t) => t.slug === (parts[4] || '').toLowerCase())
    return { tab: sub ? sub.id : 'Overview', campaign: name }
  }
  if (LEGACY_CAMPAIGN_SLUGS[slug]) return { tab: LEGACY_CAMPAIGN_SLUGS[slug], campaign: null }
  return { tab: slugToId(slug), campaign: null }
}
const tabFromHash = () => routeFromHash().tab
const campaignHash = (name, id = 'Overview') =>
  `#/app/campaigns/${encodeURIComponent(name)}/${(CAMPAIGN_TABS.find((t) => t.id === id) || CAMPAIGN_TABS[0]).slug}`

const allowedTab = (me, id) => {
  if (SALES_IDS.has(id) || id === 'Today' || id === 'Library' || id === 'Companies') return canSales(me)
  if (MKT_IDS.has(id)) return canMarketing(me)
  if (id === 'Team') return isAdmin(me)
  return true
}
const homeTab = (me, campaigns) => {
  if (me.role === 'marketing') return 'Blasts'
  if (me.role === 'sales') return (campaigns || []).length ? 'Today' : 'Training'   // a new BDR starts on Training
  return 'Campaigns'
}

export default function App({ onHome }) {
  const [me, setMe] = useState(null)               // the signed-in person, from /api/me
  const [campaigns, setCampaigns] = useState(null) // null = still loading
  const [campaign, setCampaign] = useState(() => routeFromHash().campaign || '')
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

  // The page lives in the URL (#/app/<slug>, or #/app/campaigns/<name>/<tab> inside a
  // campaign) so refresh and back/forward keep your place. A campaign tab without a
  // campaign to show falls back to the campaign list.
  const setTab = (id) => {
    if (CAMPAIGN_IDS.has(id)) {
      if (!campaign) { window.location.hash = '#/app/campaigns'; setTabState('Campaigns'); return }
      window.location.hash = campaignHash(campaign, id)
    } else {
      window.location.hash = `#/app/${idToSlug(id)}`
    }
    setTabState(id)
  }
  const openCampaign = (name, id = 'Overview') => {
    setCampaign(name)
    window.location.hash = campaignHash(name, id)
    setTabState(id)
  }
  useEffect(() => {
    const onHash = () => {
      const r = routeFromHash()
      if (r.campaign) setCampaign(r.campaign)
      setTabState(r.tab)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  // mode follows the tab (shared tabs keep the current mode)
  useEffect(() => {
    if (MKT_IDS.has(tab)) setMode('marketing')
    else if (SALES_IDS.has(tab)) setMode('sales')
  }, [tab])
  const switchMode = (m) => { setMode(m); setTab(m === 'marketing' ? 'Blasts' : 'Campaigns') }

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
        // the URL's campaign if it names one (one you can't see shows "not found"), else the first
        setCampaign((cur) => cur || (cs.includes('mycampaign') ? 'mycampaign' : cs[0] || ''))
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
      const fresh = CAMPAIGN_IDS.has(tab) && !(campaigns || []).length
      const noPage = !(window.location.hash.split('?')[0].split('/')[2] || '')   // opened the app itself, no page named
      if (!allowedTab(me, tab) || fresh || noPage) { setTab(homeTab(me, campaigns)); return }
    }
    if (!allowedTab(me, tab)) { setTab(homeTab(me, campaigns)); return }
    // an old-style link (#/app/leads): show the campaign's own address instead
    if (CAMPAIGN_IDS.has(tab) && campaign && routeFromHash().campaign === null) {
      window.history.replaceState(null, '', campaignHash(campaign, tab))
    }
  }, [me, campaigns, tab, campaign])

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
    if (tab === 'Settings') return <Settings />
    if (tab === 'Campaigns') return <CampaignList onOpen={openCampaign} onNew={() => setWizard('new')} />
    // a campaign's own pages
    if (!campaign || !campaigns.includes(campaign)) {
      return (
        <div className="empty">
          <h3>{campaign ? 'Campaign not found' : 'No campaigns yet'}</h3>
          <p className="muted">{campaign
            ? 'It may have been renamed or deleted, or it belongs to someone else.'
            : <>Create your first one on the Campaigns page.{me.role === 'sales' && ' Or ask an admin to give you an existing one.'}</>}</p>
          <div className="empty-actions"><button className="btn primary" onClick={() => setTab('Campaigns')}>All campaigns</button></div>
        </div>
      )
    }
    const page = tab === 'Overview' ? <Dashboard campaign={campaign} onNavigate={setTab} />
      : tab === 'Sequence' ? <Sequence campaign={campaign} onEdit={() => setWizard('edit')} />
      : tab === 'Leads' ? <Leads campaign={campaign} onNavigate={setTab} />
      : tab === 'Review' ? <Review campaign={campaign} />
      : tab === 'Activity' ? <Activity campaign={campaign} />
      : tab === 'Inbox' ? <Inbox campaign={campaign} /> : null
    return (
      <CampaignFrame campaign={campaign} tabs={CAMPAIGN_TABS} tab={tab} counts={counts}
        onTab={(id) => openCampaign(campaign, id)} onAll={() => setTab('Campaigns')} onEdit={() => setWizard('edit')}>
        {page}
      </CampaignFrame>
    )
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
        <div className="page-title">{CAMPAIGN_IDS.has(tab) && campaign ? campaign : tab}</div>
        {/* the instrument register: a campaign's live send state, in view on its pages */}
        {campaign && CAMPAIGN_IDS.has(tab) && (campaigns || []).includes(campaign) && (
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

        {me && (
        <nav className="nav">
          {navItems.map((n) => {
            const navCount = n.id === 'Signals' ? (status.signals_open || 0)
              : n.id === 'Today' ? dueCount : 0
            // a campaign's tabs live under Campaigns
            const active = n.id === tab || (n.id === 'Campaigns' && CAMPAIGN_IDS.has(tab))
            return (
              <button key={n.id} className={`nav-item ${active ? 'active' : ''} ${n.shared ? 'nav-op' : ''}`} onClick={() => setTab(n.id)}>
                {active && (
                  <motion.span layoutId="navpill" className="nav-pill" transition={{ type: 'spring', stiffness: 420, damping: 34 }} />
                )}
                {n.step ? <span className="nav-step">{n.step}</span> : <Icon name={n.icon} size={15} />}
                <span>{n.id}</span>
                {navCount > 0 && <span className={`nav-count ${n.id === 'Today' ? 'hot' : ''}`}>{navCount}</span>}
              </button>
            )
          })}
        </nav>
        )}

        <div className="sidebar-foot">
          <div className="foot-status">
            <span className={`dot ${error ? 'd-error' : 'd-ok'}`} />
            {error ? 'backend offline' : (me?.email || '')}
          </div>
        </div>
      </aside>

      <div className="main">
        <div className={`content ${tab === 'Training' && !error ? 'content-frame' : ''}`}>
          <AnimatePresence mode="wait">
            {/* campaign pages remount on a campaign switch; the rest (Training's frame
                above all) don't reload when the picker changes */}
            <motion.div key={CAMPAIGN_IDS.has(tab) ? `campaign:${campaign}` : tab} className="page-body" {...(reduce ? {} : pageTransition)}>
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
              setTab('Campaigns')
            }}
            onCreated={(slug) => {
              const wasEdit = wizard === 'edit'
              setWizard(false)
              // refetch (a rename removes the old slug); optimistic add meanwhile
              setCampaigns((cs) => [...new Set([...(cs || []), slug])].sort())
              api.getCampaigns().then(setCampaigns).catch(() => {})
              // a new campaign opens on its Leads; an edit stays on the tab it came from
              // (a rename moves the address to the new name)
              openCampaign(slug, wasEdit && CAMPAIGN_IDS.has(tab) ? tab : 'Leads')
            }}
          />
        )}
      </AnimatePresence>
    </div>
    </MeContext.Provider>
  )
}
