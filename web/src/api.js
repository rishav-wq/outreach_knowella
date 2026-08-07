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
export const getStatus = (c, light = false) => apiGet(`/api/status?campaign=${encodeURIComponent(c)}${light ? '&light=1' : ''}`)
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
export const renameCampaign = (campaign, new_name) => apiSend('/api/campaign/rename', 'POST', { campaign, new_name })
export const getMailboxes = (c) => apiGet(`/api/mailboxes${c ? `?campaign=${encodeURIComponent(c)}` : ''}`)
export const getSequences = (c) => apiGet(`/api/sequences${c ? `?campaign=${encodeURIComponent(c)}` : ''}`)
export const createSequence = (name, waits) => apiSend('/api/sequences/create', 'POST', { name, waits })
// delete a campaign's config (its leads stay in the DB / Library)
export const deleteCampaign = (campaign) => apiSend('/api/campaign/delete', 'POST', { campaign })
export const setMailbox = (campaign, mailbox_ids) => apiSend('/api/campaign/mailbox', 'POST', { campaign, mailbox_ids })

export const decide = (campaign, key, decision) => apiSend('/api/review/decision', 'POST', { campaign, key, decision })
// sources: where leads came from, and what each place produced
export const listSources = () => apiGet('/api/sources')
export const createSource = (s) => apiSend('/api/sources', 'POST', s)
export const setSourceNotes = (id, notes) => apiSend(`/api/sources/${encodeURIComponent(id)}/notes`, 'PUT', { notes })
export const deleteSource = (id) => apiSend(`/api/sources/${encodeURIComponent(id)}`, 'DELETE', {})
// marketing engine (Postmark broadcast stream)
export const getMarketingStatus = () => apiGet('/api/marketing/status')
export const sendMarketingTest = (to) => apiSend('/api/marketing/test', 'POST', { to })
export const getMarketingMeta = () => apiGet('/api/marketing/meta')
export const previewAudience = (filter) => apiSend('/api/marketing/preview', 'POST', filter)
export const listBlasts = () => apiGet('/api/blasts')
export const getBlast = (id) => apiGet(`/api/blasts/${encodeURIComponent(id)}`)
export const createBlast = (b) => apiSend('/api/blasts', 'POST', b)
export const updateBlast = (id, b) => apiSend(`/api/blasts/${encodeURIComponent(id)}`, 'PUT', b)
export const deleteBlast = (id) => apiSend(`/api/blasts/${encodeURIComponent(id)}`, 'DELETE', {})
export const testBlast = (id, to) => apiSend(`/api/blasts/${encodeURIComponent(id)}/test`, 'POST', { to })
export const sendBlast = (id) => apiSend(`/api/blasts/${encodeURIComponent(id)}/send`, 'POST', {})
export const listAudiences = () => apiGet('/api/audiences')
export const createAudience = (name, filter) => apiSend('/api/audiences', 'POST', { name, filter })
export const deleteAudience = (id) => apiSend(`/api/audiences/${encodeURIComponent(id)}`, 'DELETE', {})
// the flywheel's return path: Library people -> a sales campaign as fresh leads
export const promoteLeads = (keys, campaign) => apiSend('/api/library/promote', 'POST', { keys, campaign })
// LinkedIn-capture token for the browser extension (hash-stored; shown once on create)
export const getCaptureToken = () => apiGet('/api/capture_token')
export const createCaptureToken = (label) => apiSend('/api/capture_token', 'POST', { label })
export const revokeCaptureToken = (id) => apiSend(`/api/capture_token/${encodeURIComponent(id)}`, 'DELETE', {})
export const revokeLegacyCaptureToken = () => apiSend('/api/capture_token', 'DELETE', {})
// bulk-approve every pending, sendable draft (respects existing rejections)
export const approveAll = (campaign) => apiSend('/api/review/approve_all', 'POST', { campaign })
// exclude a not-a-fit lead: clears its drafts + drops it from the campaign, but keeps it in the library
export const excludeLead = (campaign, key) => apiSend('/api/review/exclude', 'POST', { campaign, key })
// master leads library: every lead across all campaigns, with function bucket + topic tags
export const getAllLeads = () => apiGet('/api/leads/all')
// bulk: remove selected leads from a campaign (kept in the library) or delete them permanently
export const bulkExcludeLeads = (campaign, keys) => apiSend('/api/leads/exclude', 'POST', { campaign, keys })
export const bulkDeleteLeads = (campaign, keys) => apiSend('/api/leads/delete', 'POST', { campaign, keys })
export const setLeadEmail = (campaign, key, email) => apiSend('/api/lead/email', 'POST', { campaign, key, email })
export const editEmail = (campaign, key, subject, body) => apiSend('/api/review/edit', 'POST', { campaign, key, subject, body })
export const refineEmail = (campaign, key, instruction) => apiSend('/api/review/refine', 'POST', { campaign, key, instruction })
export const editFollowup = (campaign, key, step, subject, body) => apiSend('/api/review/edit_followup', 'POST', { campaign, key, step, subject, body })
export const getSendingHealth = (c) => apiGet(`/api/health/sending?campaign=${encodeURIComponent(c)}`)
export const markMeeting = (campaign, key, booked = true) => apiSend('/api/lead/meeting', 'POST', { campaign, key, booked })
export const getSuppression = () => apiGet('/api/suppression')
export const addSuppression = (value, reason = '') => apiSend('/api/suppression', 'POST', { value, reason })
export const removeSuppression = (value) => apiSend('/api/suppression/remove', 'POST', { value })
export const runPipeline = (campaign, send = false, limit = null) => apiSend('/api/run', 'POST', { campaign, send, limit })

export const pull = (campaign, file, source = 'manual') => {
  const fd = new FormData()
  fd.append('campaign', campaign)
  fd.append('file', file)
  fd.append('source', source)
  return apiForm('/api/pull', fd)
}

export const pullApollo = (campaign, limit = 25) => apiSend('/api/pull/apollo', 'POST', { campaign, limit })
// Free live match count for a set of audience filters (no campaign needed — the
// wizard calls this before the campaign exists).
export const previewApollo = (icp, apollo) => apiSend('/api/preview/apollo', 'POST', { icp, apollo })
// Mark/unmark a lead as a lookalike seed — future pulls find people similar to it
export const setLookalike = (campaign, key, on) => apiSend('/api/campaign/lookalike', 'POST', { campaign, key, on })
// University-name typeahead for the alumni filter (returns Apollo school ids + names)
export const searchSchools = (q) => apiGet(`/api/apollo/schools?q=${encodeURIComponent(q)}`)
