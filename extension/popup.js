// Knowella Outreach — LinkedIn commenter capture.
//
// Risk posture (deliberate): the page is only ever READ — no DOM writes, no
// synthetic events, no LinkedIn API calls, no injected UI. Reads happen in
// Chrome's isolated world (invisible to the page's own scripts), either once
// per "Scan" click or — when you toggle auto-scan — via a passive
// MutationObserver that accumulates commenters while YOU scroll. You do all
// the scrolling and clicking; nothing is automated. LinkedIn is a pointer
// (name + profile URL + headline); contact data comes from Apollo.

const $ = (id) => document.getElementById(id)

let cfg = { appUrl: '', token: '' }
let tabId = null
let captured = []          // [{name, profile_url, headline}] accumulated across scans
let postUrl = ''
let watching = false
let lockActivity = ''      // capture locks to the post scanned FIRST; Clear list unlocks

const norm = (u) => (u || '').toLowerCase().split('?')[0].split('#')[0]
  .replace('https://', '').replace('http://', '').replace(/^www\./, '').replace(/\/$/, '')

// ---------- state ----------
const sessionKey = () => `cap_${tabId}`
const loadState = async () => {
  const d = await chrome.storage.session.get(sessionKey())
  const s = d[sessionKey()]
  captured = s?.items || []
  postUrl = s?.postUrl || ''
  lockActivity = s?.lock || ''
  renderCount(0)
}
const saveState = () =>
  chrome.storage.session.set({ [sessionKey()]: { items: captured, postUrl, lock: lockActivity } })

// merge a scrape result into the accumulated list; returns how many were new.
// The first batch with activity ids locks capture to that post (majority id), so
// scrolling past other feed posts never sweeps in their commenters.
function mergeFound(found) {
  if (!lockActivity) {
    const counts = {}
    for (const c of found || []) if (c.activity) counts[c.activity] = (counts[c.activity] || 0) + 1
    lockActivity = (Object.entries(counts).sort((a, b) => b[1] - a[1])[0] || [])[0] || ''
  }
  const known = new Set(captured.map((c) => norm(c.profile_url)))
  let added = 0
  for (const c of found || []) {
    if (lockActivity && c.activity && c.activity !== lockActivity) continue   // another post's comment
    const k = norm(c.profile_url)
    if (!k || known.has(k)) continue
    known.add(k)
    captured.push({ name: c.name, profile_url: c.profile_url, headline: c.headline })
    added++
  }
  return added
}

// ---------- UI ----------
function renderCount(delta) {
  $('n').textContent = captured.length
  $('delta').textContent = delta > 0 ? `+${delta} new` : (captured.length
    ? (watching ? 'auto-scanning — just scroll' : 'scroll & scan again to add more')
      + (lockActivity ? ' · locked to this post (Clear list to switch)' : '')
    : '')
  $('send').hidden = captured.length === 0
  $('clear').hidden = captured.length === 0
  $('send').textContent = `Send ${captured.length} to campaign`
  const list = $('list')
  list.hidden = captured.length === 0
  list.innerHTML = ''
  if (captured.length > 80) {   // preview cap — everything is still captured & sent
    const note = document.createElement('div')
    note.style.cssText = 'color:var(--muted);font-style:italic'
    note.textContent = `showing the 80 most recent of ${captured.length} captured — all ${captured.length} will be sent`
    list.appendChild(note)
  }
  for (const c of captured.slice(-80).reverse()) {
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

// ---------- the page-side agent (serialized into the tab; self-contained) ----------
// mode: 'scan' = one-shot scrape · 'watch' = install a passive MutationObserver that
// re-scrapes (debounced) as content loads and messages the panel · 'stop' = remove it.
function pageAgent(mode) {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim()
  const badgeRe = /^(•|·|✓|Author|Following|Follow|Premium|Verified|Edited|\(edited\)|(1st|2nd|3rd)\+?$|\d+\s?(mo|[smhdwy])\b|Like|Reply|React|See translation|View|Load)/i
  const foldDup = (s) => {   // LinkedIn duplicates names via aria spans ("Jane DoeJane Doe")
    const half = Math.floor(s.length / 2)
    return half > 2 && s.slice(0, half).trim() === s.slice(half).trim() ? s.slice(0, half).trim() : s
  }
  // a11y/badge suffixes stack ("Jane Doe Premium Profile Following") — strip until stable
  const suffixRe = /(\s*[•·✓].*|\s*\((He|She|They)[^)]*\)|,?\s+Open to work|\s+(Verified|Premium)(\s+Profile)?|\s+(Following|Follow|Author|Connect|Message)|\s+(1st|2nd|3rd\+?))$/i
  const cleanName = (s) => {
    let out = foldDup(clean(s)), prev
    do { prev = out; out = out.replace(suffixRe, '').trim() } while (out !== prev)
    return out
  }

  function scrape() {
    const items = []
    const containers = document.querySelectorAll(
      '[componentkey*="replaceableComment"], ' +
      'article[class*="comments-comment"], div[class*="comments-comment-entity"], div[class*="comments-comment-item"], ' +
      '[data-view-name*="comment-entity"], [data-view-name="comment"], [data-view-name*="comments-comment"]')
    for (const el of containers) {
      const cls = String(el.className || '')
      if (/comment-box|texteditor|comment-social/.test(cls)) continue   // the reply editor, not a comment
      // a comment's componentkey names its post's activity id — reported per item so the
      // panel can lock capture to ONE post (URL activity ids are unreliable: share URNs
      // differ from the comments' original-post URNs)
      const ck = el.getAttribute('componentkey') || ''
      const ckActivity = (ck.match(/activity[:%](\d{8,})/) || [])[1] || ''
      const a = el.querySelector('a[href*="/in/"]')
      if (!a) continue
      const href = (a.href || '').split('?')[0].split('#')[0]
      if (!href.includes('/in/')) continue
      const nameEl = el.querySelector('[class*="description-title"], [class*="actor-name"], [class*="__name"]')
      // in the obfuscated DOM the author anchor wraps only the avatar image — the
      // name/headline are the container's first text lines instead
      const aLines = (a.innerText || '').split('\n').map(clean).filter(Boolean)
      const boxLines = (el.innerText || '').split('\n').map(clean).filter(Boolean)
      let name = cleanName(nameEl ? nameEl.textContent : (aLines[0] || boxLines[0] || ''))
      if (!name) continue
      const headEl = el.querySelector('[class*="description-subtitle"], [class*="actor-headline"], [class*="__headline"]')
      let headline = clean(headEl ? headEl.textContent : '')
      if (!headline) {
        const pool = aLines.length > 1 ? aLines : boxLines
        const iName = pool.findIndex((l) => cleanName(l) === name)
        headline = pool.slice(iName + 1, iName + 6).find((l) =>
          l.length > 11 && !badgeRe.test(l) && cleanName(l) !== name && !name.startsWith(cleanName(l))) || ''
      }
      items.push({ name, profile_url: href, headline, activity: ckActivity })
    }
    return items
  }

  if (mode === 'stop') {
    if (window.__knowellaWatch) { window.__knowellaWatch.disconnect(); window.__knowellaWatch = null }
    return { watching: false }
  }
  if (mode === 'watch') {
    if (!window.__knowellaWatch) {
      let t = null
      const push = () => {
        try {
          chrome.runtime.sendMessage({ type: 'knowella-commenters',
            url: location.href.split('?')[0], found: scrape() })
        } catch (e) { /* panel closed — observer keeps quietly deduping later */ }
      }
      const obs = new MutationObserver(() => { clearTimeout(t); t = setTimeout(push, 700) })
      obs.observe(document.body, { childList: true, subtree: true })
      window.__knowellaWatch = obs
    }
    return { watching: true, url: location.href.split('?')[0], found: scrape() }
  }

  // one-shot scan (+ debug when nothing matches, so selector fixes never need guesswork)
  const found = scrape()
  const out = { url: location.href.split('?')[0], found, blocks: found.length }
  if (!found.length) {
    const dbg = { viewNames: {}, classes: {}, componentkeys: {}, articles: document.querySelectorAll('article').length,
                  profileLinks: document.querySelectorAll('a[href*="/in/"]').length }
    document.querySelectorAll('[componentkey]').forEach((e) => {
      const v = (e.getAttribute('componentkey') || '').replace(/urn:li:[^)]*\)?/g, 'URN').slice(0, 40)
      dbg.componentkeys[v] = (dbg.componentkeys[v] || 0) + 1
    })
    document.querySelectorAll('[data-view-name]').forEach((e) => {
      const v = e.getAttribute('data-view-name') || ''
      if (/comment/i.test(v)) dbg.viewNames[v] = (dbg.viewNames[v] || 0) + 1
    })
    document.querySelectorAll('[class*="omment"]').forEach((e) => {
      String(e.className).split(/\s+/).forEach((c) => { if (/omment/i.test(c)) dbg.classes[c] = (dbg.classes[c] || 0) + 1 })
    })
    out.debug = dbg
  }
  return out
}

// ---------- actions ----------
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  return tab
}

async function runAgent(mode) {
  const tab = await activeTab()
  if (!tab) { msg('No active tab found.', 'err'); return null }
  if (tab.url && !/linkedin\.com/.test(tab.url)) {
    msg('This isn’t LinkedIn — open the post there first.', 'err'); return null
  }
  if (tab.id !== tabId) { tabId = tab.id; await loadState() }   // panel stayed open across a tab switch
  try {
    const [r] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: pageAgent, args: [mode] })
    return r?.result ?? null
  } catch (e) {
    msg(`Could not read the page: ${e.message}. Reload the LinkedIn tab and try again.`, 'err')
    return null
  }
}

async function scan() {
  msg('')
  const res = await runAgent('scan')
  if (!res) return
  if (!res.blocks) {
    msg('No comment blocks found. Open the post itself and expand its comments — or LinkedIn changed its markup (the extension needs a selector update).', 'err')
    if (res.debug) {
      const list = $('list')
      list.hidden = false
      const pre = document.createElement('div')
      pre.style.cssText = 'white-space:pre-wrap;font-family:monospace;font-size:10.5px;user-select:text'
      pre.textContent = 'DEBUG (copy this):\n' + JSON.stringify(res.debug, null, 1)
      list.innerHTML = ''
      list.appendChild(pre)
    }
    return
  }
  postUrl = res.url
  const added = mergeFound(res.found)
  await saveState()
  renderCount(added)
}

async function toggleWatch() {
  msg('')
  if (watching) {
    await runAgent('stop')
    watching = false
  } else {
    const res = await runAgent('watch')
    if (!res) return
    watching = true
    postUrl = res.url
    const added = mergeFound(res.found)
    await saveState()
    renderCount(added)
  }
  $('watch').textContent = watching ? 'Auto-scan: ON — just scroll' : 'Auto-scan while I scroll: OFF'
  $('watch').classList.toggle('on', watching)
  renderCount(0)
}

// live results from the watcher as the user scrolls
chrome.runtime.onMessage.addListener((m, sender) => {
  if (m?.type !== 'knowella-commenters' || sender.tab?.id !== tabId) return
  postUrl = m.url || postUrl
  const added = mergeFound(m.found)
  if (added > 0) { saveState(); renderCount(added) }
})

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

  const tab = await activeTab()
  if (tab) { tabId = tab.id; await loadState() }

  $('gear').onclick = () => document.body.classList.toggle('setup')
  $('save').onclick = async () => {
    cfg = { appUrl: $('appUrl').value.trim().replace(/\/$/, ''), token: $('token').value.trim() }
    await chrome.storage.local.set(cfg)
    document.body.classList.remove('setup')
    await loadCampaigns()
  }
  $('scan').onclick = scan
  $('watch').onclick = toggleWatch
  $('send').onclick = send
  $('clear').onclick = async () => { captured = []; lockActivity = ''; await saveState(); renderCount(0); msg('') }
}

init()
