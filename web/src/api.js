// Thin client for the FastAPI backend. Calls it directly (CORS-enabled), so it
// works even if the Vite proxy is broken (e.g. by editor extensions).
// Every request carries the Clerk session token (when signed in); the backend
// verifies it. Without Clerk configured, getAuthToken() returns '' and the
// backend leaves the API open — so local dev is unchanged.
import { getAuthToken } from './auth'

// VITE_API_BASE is set per env: localhost in web/.env (dev), empty in
// web/.env.production (same-origin, since FastAPI serves this app in prod).
const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8010'
const u = (p) => `${BASE}${p}`
const json = (r) => {
  if (!r.ok) return r.text().then((t) => { throw new Error(t || r.statusText) })
  return r.json()
}

async function authHeaders(extra = {}) {
  const t = await getAuthToken()
  return t ? { ...extra, Authorization: `Bearer ${t}` } : { ...extra }
}

const apiGet = (p) => authHeaders().then((h) => fetch(u(p), { headers: h })).then(json)
const apiSend = (p, method, body) =>
  authHeaders({ 'Content-Type': 'application/json' })
    .then((h) => fetch(u(p), { method, headers: h, body: JSON.stringify(body) }))
    .then(json)
const apiForm = (p, fd) =>
  authHeaders().then((h) => fetch(u(p), { method: 'POST', headers: h, body: fd })).then(json)

export const getCampaigns = () => apiGet('/api/campaigns')
export const createCampaign = (payload) => apiSend('/api/campaigns', 'POST', payload)
export const getStatus = (c) => apiGet(`/api/status?campaign=${encodeURIComponent(c)}`)
export const getLeads = (c) => apiGet(`/api/leads?campaign=${encodeURIComponent(c)}`)
export const getReview = (c) => apiGet(`/api/review?campaign=${encodeURIComponent(c)}`)
export const getBoard = (c) => apiGet(`/api/board?campaign=${encodeURIComponent(c)}`)
export const getLead = (c, key) => apiGet(`/api/lead?campaign=${encodeURIComponent(c)}&key=${encodeURIComponent(key)}`)
export const getRunStatus = (c) => apiGet(`/api/run/status?campaign=${encodeURIComponent(c)}`)
export const getInbox = (c) => apiGet(`/api/inbox?campaign=${encodeURIComponent(c)}`)
export const getThread = (c, id) => apiGet(`/api/inbox/thread?campaign=${encodeURIComponent(c)}&thread_id=${encodeURIComponent(id)}`)
export const getAnalytics = (c) => apiGet(`/api/analytics?campaign=${encodeURIComponent(c)}`)
export const getAB = (c) => apiGet(`/api/ab?campaign=${encodeURIComponent(c)}`)
export const getCampaignConfig = (c) => apiGet(`/api/campaign/config?campaign=${encodeURIComponent(c)}`)
export const updateCampaign = (campaign, patch) => apiSend('/api/campaign/update', 'POST', { campaign, ...patch })
export const getMailboxes = (c) => apiGet(`/api/mailboxes${c ? `?campaign=${encodeURIComponent(c)}` : ''}`)
export const getSequences = (c) => apiGet(`/api/sequences${c ? `?campaign=${encodeURIComponent(c)}` : ''}`)
export const setMailbox = (campaign, mailbox_id) => apiSend('/api/campaign/mailbox', 'POST', { campaign, mailbox_id })

export const decide = (campaign, key, decision) => apiSend('/api/review/decision', 'POST', { campaign, key, decision })
export const setLeadEmail = (campaign, key, email) => apiSend('/api/lead/email', 'POST', { campaign, key, email })
export const editEmail = (campaign, key, subject, body) => apiSend('/api/review/edit', 'POST', { campaign, key, subject, body })
export const refineEmail = (campaign, key, instruction) => apiSend('/api/review/refine', 'POST', { campaign, key, instruction })
export const runPipeline = (campaign, send = false, limit = null) => apiSend('/api/run', 'POST', { campaign, send, limit })

export const pull = (campaign, file, source = 'manual') => {
  const fd = new FormData()
  fd.append('campaign', campaign)
  fd.append('file', file)
  fd.append('source', source)
  return apiForm('/api/pull', fd)
}

export const pullApollo = (campaign, limit = 25) => apiSend('/api/pull/apollo', 'POST', { campaign, limit })
