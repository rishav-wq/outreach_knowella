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
  const badgeRe = /^(•|·|✓|Author|Following|Follow|Premium|Verified|Edited|\(edited\)|(1st|2nd|3rd)\+?$|\d+\s?(mo|[smhdwy])\b|Like|Reply|React|See translation|View|Load)/i
  const foldDup = (s) => {   // LinkedIn duplicates names via aria spans ("Jane DoeJane Doe")
    const half = Math.floor(s.length / 2)
    return half > 2 && s.slice(0, half).trim() === s.slice(half).trim() ? s.slice(0, half).trim() : s
  }
  const cleanName = (s) => foldDup(clean(s)).replace(/\s*[•·✓].*$/, '')
    .replace(/\s*\((He|She|They)[^)]*\)/i, '').replace(/\s*(1st|2nd|3rd\+?|Author|Premium)\s*$/i, '').trim()
  const items = []
  // Layered selectors, most-precise first:
  //  1. componentkey="replaceableComment_urn:li:comment:…" — the new obfuscated DOM
  //     names its components even though every class is hashed (live-verified 2026-07-30).
  //  2. classic comments-comment-* class names (older markup).
  //  3. data-view-name variants (intermediate rollouts).
  const containers = document.querySelectorAll(
    '[componentkey*="replaceableComment"], ' +
    'article[class*="comments-comment"], div[class*="comments-comment-entity"], div[class*="comments-comment-item"], ' +
    '[data-view-name*="comment-entity"], [data-view-name="comment"], [data-view-name*="comments-comment"]')
  for (const el of containers) {
    const cls = String(el.className || '')
    if (/comment-box|texteditor|comment-social/.test(cls)) continue   // the reply editor, not a comment
    const a = el.querySelector('a[href*="/in/"]')
    if (!a) continue
    const href = (a.href || '').split('?')[0].split('#')[0]
    if (!href.includes('/in/')) continue
    const nameEl = el.querySelector('[class*="description-title"], [class*="actor-name"], [class*="__name"]')
    // In the new DOM the author anchor wraps only the avatar IMAGE — the name and
    // headline are the container's first text lines instead.
    const aLines = (a.innerText || '').split('\n').map(clean).filter(Boolean)
    const boxLines = (el.innerText || '').split('\n').map(clean).filter(Boolean)
    let name = cleanName(nameEl ? nameEl.textContent : (aLines[0] || boxLines[0] || ''))
    if (!name) continue
    const headEl = el.querySelector('[class*="description-subtitle"], [class*="actor-headline"], [class*="__headline"]')
    let headline = clean(headEl ? headEl.textContent : '')
    if (!headline) {   // first non-badge line after the name, from anchor text or the container
      const pool = aLines.length > 1 ? aLines : boxLines
      const iName = pool.findIndex((l) => cleanName(l) === name)
      headline = pool.slice(iName + 1, iName + 5).find((l) => l.length > 11 && !badgeRe.test(l) && cleanName(l) !== name) || ''
    }
    items.push({ name, profile_url: href, headline })
  }
  let blocks = containers.length

  // Layer 3 — structural fallback for LinkedIn's fully-obfuscated markup (no semantic
  // classes, no data-view-name). Shape of a comment that survives any renaming:
  // a VISIBLE profile link whose text is a person's name, inside a small block that
  // also carries a relative-time token ("5d", "23h"). That block ≈ one comment.
  if (!blocks) {
    const seenHref = new Set()
    const timeRe = /(^|\s)\d+\s?(mo|[smhdwy])(\b|$)/
    const badgeRe = /^(•|·|Author|Following|Follow|Premium|Verified|Edited|\(edited\)|(1st|2nd|3rd)\+?$|\d+\s?(mo|[smhdwy])\b|Like|Reply|React|See translation)/i
    for (const a of document.querySelectorAll('a[href*="/in/"]')) {
      let name = clean(a.innerText)
      if (!name || name.length > 80) continue                    // avatar-only or junk anchors
      if (!(a.offsetWidth || a.offsetHeight)) continue           // hidden (menus, overlays)
      const href = (a.href || '').split('?')[0].split('#')[0]
      if (!href.includes('/in/') || seenHref.has(href)) continue
      // smallest ancestor that reads like ONE comment (has a time token, isn't the whole feed)
      let node = a.parentElement, box = null
      for (let d = 0; node && d < 7; d++, node = node.parentElement) {
        const t = node.innerText || ''
        if (t.length > 4000) break                               // crossed into the post/feed level
        if (timeRe.test(t)) { box = node; break }
      }
      if (!box) continue
      const half = Math.floor(name.length / 2)
      if (half > 2 && name.slice(0, half).trim() === name.slice(half).trim()) name = name.slice(0, half).trim()
      name = name.replace(/\s*[•·].*$/, '').replace(/\s*\((He|She|They)[^)]*\)/i, '').trim()
      const lines = (box.innerText || '').split('\n').map(clean).filter(Boolean)
      const iName = lines.findIndex((l) => l === name || l.startsWith(name))
      let headline = ''
      for (let j = iName + 1; j >= 0 && j < Math.min(iName + 5, lines.length); j++) {
        const l = lines[j]
        if (l === name || badgeRe.test(l)) continue
        if (l.length < 6) continue
        headline = l; break
      }
      seenHref.add(href)
      items.push({ name, profile_url: href, headline })
    }
    blocks = items.length
  }

  const out = { url: location.href.split('?')[0], found: items, blocks }
  if (!blocks) {
    // Debug probe: what does the markup look like HERE? Shown in the panel so
    // selector updates never need guesswork.
    const dbg = { viewNames: {}, classes: {}, ariaComment: {}, roles: {},
                  articles: document.querySelectorAll('article').length,
                  profileLinks: document.querySelectorAll('a[href*="/in/"]').length,
                  anchorSamples: [] }
    document.querySelectorAll('[data-view-name]').forEach((e) => {
      const v = e.getAttribute('data-view-name') || ''
      if (/comment/i.test(v)) dbg.viewNames[v] = (dbg.viewNames[v] || 0) + 1
    })
    document.querySelectorAll('[class*="omment"]').forEach((e) => {
      String(e.className).split(/\s+/).forEach((c) => {
        if (/omment/i.test(c)) dbg.classes[c] = (dbg.classes[c] || 0) + 1
      })
    })
    document.querySelectorAll('[aria-label]').forEach((e) => {
      const v = e.getAttribute('aria-label') || ''
      if (/comment/i.test(v)) dbg.ariaComment[v.slice(0, 60)] = (dbg.ariaComment[v.slice(0, 60)] || 0) + 1
    })
    document.querySelectorAll('[role]').forEach((e) => {
      const v = e.getAttribute('role')
      dbg.roles[v] = (dbg.roles[v] || 0) + 1
    })
    // three visible named profile anchors + their 5-level ancestry text heads
    let n = 0
    for (const a of document.querySelectorAll('a[href*="/in/"]')) {
      if (n >= 3) break
      const nm = clean(a.innerText)
      if (!nm || !(a.offsetWidth || a.offsetHeight)) continue
      const chain = []
      let p = a.parentElement
      for (let d = 0; p && d < 5; d++, p = p.parentElement) {
        chain.push(`${p.tagName}:${(p.innerText || '').slice(0, 80).replace(/\n/g, '¶')}`)
      }
      dbg.anchorSamples.push({ name: nm.slice(0, 40), chain })
      n++
    }
    out.debug = dbg
  }
  return out
}

// ---------- actions ----------
async function scan() {
  msg('')
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab) { msg('No active tab found.', 'err'); return }
  // tab.url is only visible while activeTab is granted (per toolbar click, lapses on
  // navigation) — so an unreadable URL is NOT proof we're off LinkedIn. Only block when
  // we can positively see a non-LinkedIn site; otherwise try the scan and let Chrome's
  // permission error tell us to re-grant.
  if (tab.url && !/linkedin\.com/.test(tab.url)) {
    msg('This isn’t LinkedIn — open the post there, then Scan.', 'err'); return
  }
  if (tab.id !== tabId) { tabId = tab.id; await loadState() }   // panel stayed open across a tab switch
  let res
  try {
    const [r] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: scrapeComments })
    res = r?.result
  } catch (e) {
    msg(`Could not read the page: ${e.message}. Reload the LinkedIn tab and Scan again.`, 'err')
    return
  }
  if (!res || res.blocks === 0) {
    msg('No comment blocks found. Open the post itself and expand its comments — or LinkedIn changed its markup (the extension needs a selector update).', 'err')
    if (res?.debug) {   // show what the page's comment markup actually looks like
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
