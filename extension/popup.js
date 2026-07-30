// Knowella Outreach — LinkedIn commenter capture.
//
// Risk posture (deliberate): NOTHING runs on LinkedIn except at the moment you
// click "Scan" (activeTab + scripting — no content scripts, no host permissions,
// no background access, no auto-scroll, no auto-clicking). The scan reads ONLY
// the comment blocks you already loaded by scrolling yourself. LinkedIn is used
// as a pointer (name + profile URL + headline); contact data comes from Apollo.

const $ = (id) => document.getElementById(id)

let cfg = { appUrl: '', token: '' }
let tabId = null
let captured = []          // [{name, profile_url, headline}] accumulated across scans
let postUrl = ''

const norm = (u) => (u || '').toLowerCase().split('?')[0].split('#')[0]
  .replace('https://', '').replace('http://', '').replace(/^www\./, '').replace(/\/$/, '')

// ---------- state ----------
const sessionKey = () => `cap_${tabId}`
const loadState = async () => {
  const d = await chrome.storage.session.get(sessionKey())
  const s = d[sessionKey()]
  if (s) { captured = s.items || []; postUrl = s.postUrl || '' }
  renderCount(0)
}
const saveState = () =>
  chrome.storage.session.set({ [sessionKey()]: { items: captured, postUrl } })

// ---------- UI ----------
function renderCount(delta) {
  $('n').textContent = captured.length
  $('delta').textContent = delta > 0 ? `+${delta} new this scan` : (captured.length ? 'scroll & scan again to add more' : '')
  $('send').hidden = captured.length === 0
  $('clear').hidden = captured.length === 0
  $('send').textContent = `Send ${captured.length} to campaign`
  const list = $('list')
  list.hidden = captured.length === 0
  list.innerHTML = ''
  for (const c of captured.slice(-60).reverse()) {
    const row = document.createElement('div')
    row.textContent = c.name || c.profile_url
    if (c.headline) {
      const s = document.createElement('span')
      s.textContent = ` — ${c.headline.slice(0, 60)}`
      row.appendChild(s)
    }
    list.appendChild(row)
  }
}

function msg(text, cls = '') {
  $('msg').innerHTML = ''
  if (!text) return
  const d = document.createElement('div')
  d.className = `msg ${cls}`
  d.textContent = text
  $('msg').appendChild(d)
}

// ---------- the page-side scan (serialized into the tab on click) ----------
function scrapeComments() {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim()
  const items = []
  const containers = document.querySelectorAll(
    'article[class*="comments-comment"], div[class*="comments-comment-entity"], div[class*="comments-comment-item"]')
  for (const el of containers) {
    const cls = el.className || ''
    if (/comment-box|texteditor|comment-social/.test(cls)) continue   // the reply editor, not a comment
    const a = el.querySelector('a[href*="/in/"]')
    if (!a) continue
    const href = (a.href || '').split('?')[0].split('#')[0]
    if (!href.includes('/in/')) continue
    const nameEl = el.querySelector('[class*="description-title"], [class*="actor-name"], [class*="__name"]')
    let name = clean(nameEl ? nameEl.textContent : a.textContent)
    // LinkedIn duplicates names via aria spans ("Jane DoeJane Doe") — fold them
    const half = Math.floor(name.length / 2)
    if (half > 2 && name.slice(0, half).trim() === name.slice(half).trim()) name = name.slice(0, half).trim()
    name = name.replace(/\s*[•·].*$/, '').replace(/\s*\((He|She|They)[^)]*\)/i, '')
               .replace(/\s*(1st|2nd|3rd\+?|Author|Premium)\s*$/i, '').trim()
    const headEl = el.querySelector('[class*="description-subtitle"], [class*="actor-headline"], [class*="__headline"]')
    const headline = clean(headEl ? headEl.textContent : '')
    items.push({ name, profile_url: href, headline })
  }
  return { url: location.href.split('?')[0], found: items, blocks: containers.length }
}

// ---------- actions ----------
async function scan() {
  msg('')
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab || !/linkedin\.com/.test(tab.url || '')) {
    msg('Open a LinkedIn post first, then click Scan.', 'err'); return
  }
  if (tab.id !== tabId) { tabId = tab.id; await loadState() }   // panel stayed open across a tab switch
  let res
  try {
    const [r] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: scrapeComments })
    res = r?.result
  } catch (e) {
    // activeTab is granted per toolbar click and lapses when the tab navigates
    msg('Chrome needs a fresh grant for this page: click the extension’s toolbar icon once, then Scan again.', 'err')
    return
  }
  if (!res || res.blocks === 0) {
    msg('No comment blocks found. Open the post itself and expand its comments — or LinkedIn changed its markup (the extension needs a selector update).', 'err')
    return
  }
  postUrl = res.url
  const known = new Set(captured.map((c) => norm(c.profile_url)))
  let added = 0
  for (const c of res.found) {
    const k = norm(c.profile_url)
    if (!k || known.has(k)) continue
    known.add(k); captured.push(c); added++
  }
  await saveState()
  renderCount(added)
}

async function send() {
  const campaign = $('campaign').value
  if (!campaign) { msg('Pick a campaign first.', 'err'); return }
  $('send').disabled = true
  msg('Sending…')
  try {
    const r = await fetch(`${cfg.appUrl}/api/linkedin/capture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Capture-Token': cfg.token },
      body: JSON.stringify({ campaign, post_url: postUrl, commenters: captured }),
    })
    if (!r.ok) throw new Error((await r.text()).slice(0, 200))
    const d = await r.json()
    captured = []
    await saveState()
    renderCount(0)
    msg(`Added ${d.added} lead${d.added === 1 ? '' : 's'} to ${campaign} — ${d.with_email} with email, ${d.no_email} without` +
        `${d.duplicates ? `, ${d.duplicates} already captured` : ''}${d.suppressed ? `, ${d.suppressed} suppressed` : ''}` +
        `${d.credits_used ? ` · ${d.credits_used} Apollo credits` : ''}. Review them in the app.`, 'ok')
  } catch (e) {
    msg(`Send failed: ${e.message}`, 'err')
  } finally {
    $('send').disabled = false
  }
}

async function loadCampaigns() {
  const sel = $('campaign')
  sel.innerHTML = '<option value="">loading…</option>'
  try {
    const r = await fetch(`${cfg.appUrl}/api/linkedin/campaigns`, { headers: { 'X-Capture-Token': cfg.token } })
    if (r.status === 401) throw new Error('token rejected — regenerate it in the app’s Settings and paste it here (⚙)')
    if (!r.ok) throw new Error(`app returned ${r.status}`)
    const d = await r.json()
    sel.innerHTML = ''
    for (const name of d.campaigns || []) {
      const o = document.createElement('option')
      o.value = o.textContent = name
      sel.appendChild(o)
    }
    const { lastCampaign } = await chrome.storage.local.get('lastCampaign')
    if (lastCampaign && d.campaigns.includes(lastCampaign)) sel.value = lastCampaign
    sel.onchange = () => chrome.storage.local.set({ lastCampaign: sel.value })
  } catch (e) {
    sel.innerHTML = '<option value="">unavailable</option>'
    msg(`Can’t reach the app: ${e.message}`, 'err')
  }
}

// ---------- setup ----------
async function init() {
  const st = await chrome.storage.local.get(['appUrl', 'token'])
  cfg = { appUrl: (st.appUrl || '').replace(/\/$/, ''), token: st.token || '' }
  $('appUrl').value = cfg.appUrl || 'https://outreach.knowella.com'
  $('token').value = cfg.token
  if (!cfg.appUrl || !cfg.token) document.body.classList.add('setup')
  else { await loadCampaigns() }

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (tab) { tabId = tab.id; await loadState() }

  $('gear').onclick = () => document.body.classList.toggle('setup')
  $('save').onclick = async () => {
    cfg = { appUrl: $('appUrl').value.trim().replace(/\/$/, ''), token: $('token').value.trim() }
    await chrome.storage.local.set(cfg)
    document.body.classList.remove('setup')
    await loadCampaigns()
  }
  $('scan').onclick = scan
  $('send').onclick = send
  $('clear').onclick = async () => { captured = []; await saveState(); renderCount(0); msg('') }
}

init()
