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
let dismissed = new Set()  // profile urls you removed — never re-added by a later scan

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
  dismissed = new Set(s?.dismissed || [])
  renderCount(0)
}
const saveState = () =>
  chrome.storage.session.set({ [sessionKey()]: { items: captured, postUrl, lock: lockActivity,
                                                 dismissed: [...dismissed] } })

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
    if (!k || known.has(k) || dismissed.has(k)) continue   // removed people stay removed
    known.add(k)
    captured.push({ name: c.name, profile_url: c.profile_url, headline: c.headline })
    added++
  }
  return added
}

// ---------- UI ----------
function renderCount(delta) {
  $('n').textContent = captured.length
  $('delta').className = delta > 0 ? 'delta plus' : 'delta'   // teal pill only for growth
  $('delta').textContent = delta > 0 ? `+${delta} new` : (captured.length
    ? (watching ? 'auto-scanning — just scroll' : 'scroll & scan again to add more')
      + (lockActivity ? ' · locked to this post' : '')
    : '')
  $('send').hidden = captured.length === 0
  $('clear').hidden = captured.length === 0
  $('export').hidden = captured.length === 0
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
    row.className = 'cap-row'
    const txt = document.createElement('span')
    txt.className = 'cap-txt'
    txt.textContent = c.name || c.profile_url
    if (c.headline) {
      const s = document.createElement('span')
      s.textContent = ` — ${c.headline.slice(0, 60)}`
      txt.appendChild(s)
    }
    // drop an obviously-irrelevant person on the spot — saves an Apollo credit and
    // keeps them out of later scans (dismissed, not just deleted)
    const del = document.createElement('button')
    del.className = 'cap-del'
    del.textContent = '×'
    del.title = 'Remove — and don’t re-add on the next scan'
    del.onclick = async () => {
      dismissed.add(norm(c.profile_url))
      captured = captured.filter((x) => norm(x.profile_url) !== norm(c.profile_url))
      await saveState()
      renderCount(0)
    }
    row.appendChild(txt)
    row.appendChild(del)
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
        // the headline sits between the name and the timestamp; anything after the
        // timestamp is the comment body — never pick from there (author replies have
        // no Follow button, so the body used to leak in as the 'headline')
        let end = pool.findIndex((l, i) => i > iName && /^(\(edited\)\s*)?\d+\s?(mo|[smhdwy])\b/.test(l))
        if (end === -1) end = Math.min(iName + 6, pool.length)
        headline = pool.slice(iName + 1, end).find((l) =>
          l.length > 6 && !badgeRe.test(l) && cleanName(l) !== name && !name.startsWith(cleanName(l))) || ''
      }
      items.push({ name, profile_url: href, headline, activity: ckActivity })
    }

    // REACTIONS: LinkedIn lists reactors in a modal ("All 117"). Far more numerous
    // than commenters — a post with 4 comments can have 117 reactions — and still a
    // self-selected signal, just weaker intent. Everything in the open modal belongs
    // to the post it was opened from, so no activity id is needed to scope it.
    //
    // Detection is STRUCTURAL, not markup-based: this build carries no role="dialog",
    // so we look for what a modal physically IS — a tall, fixed-position overlay —
    // and take the profile links inside it.
    const inOverlay = (el) => {
      let n = el
      for (let d = 0; n && d < 14; d++, n = n.parentElement) {
        if (n.getAttribute && (n.getAttribute('role') === 'dialog' || n.getAttribute('aria-modal') === 'true')) return true
        try {
          const s = getComputedStyle(n)
          if ((s.position === 'fixed' || s.position === 'absolute') && n.offsetHeight > 240 && n.offsetWidth > 240) {
            // an overlay panel, not the page itself
            if (n.offsetWidth < window.innerWidth * 0.9) return true
          }
        } catch (e) { /* detached node */ }
      }
      return false
    }
    const modalLinks = [...document.querySelectorAll('a[href*="/in/"]')].filter(
      (a) => (a.offsetWidth || a.offsetHeight) && inOverlay(a))
    if (modalLinks.length) {
      const seenHref = new Set(items.map((i) => i.profile_url))
      for (const a of modalLinks) {
        const href = (a.href || '').split('?')[0].split('#')[0]
        if (!href.includes('/in/') || seenHref.has(href)) continue
        if (!(a.offsetWidth || a.offsetHeight)) continue
        // walk up to the row that carries both the name and the headline
        let row = a
        for (let d = 0; d < 4 && row.parentElement; d++) {
          row = row.parentElement
          if ((row.innerText || '').split('\n').map(clean).filter(Boolean).length >= 2) break
        }
        const lines = (row.innerText || '').split('\n').map(clean).filter(Boolean)
        if (!lines.length) continue
        const name = cleanName(lines[0])
        if (!name) continue
        const headline = lines.slice(1).find((l) =>
          l.length > 6 && !badgeRe.test(l) && cleanName(l) !== name) || ''
        seenHref.add(href)
        items.push({ name, profile_url: href, headline, activity: '', source: 'reaction' })
      }
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
  const out = { url: location.href.split('?')[0], found, blocks: found.length,
                counts: { total: found.length, reactions: found.filter((f) => f.source === 'reaction').length } }
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
    msg('Nothing found. Expand the post’s comments, or open its reactions list ("117 · Like") and scan again — or LinkedIn changed its markup (the extension needs a selector update).', 'err')
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
  // say what came from where — so "it's not capturing" is never a guess again
  if (res.counts) {
    const c = res.counts
    msg(`Scanned: ${c.total} on the page (${c.reactions} from the reactions list, ${c.total - c.reactions} from comments) → ${added} new.`
        + (c.reactions === 0 ? ' If the reactions modal is open and this says 0, the overlay wasn’t detected — tell me.' : ''))
  }
}

// Tear down the page-side observer and sync the toggle's UI. Used by the toggle
// itself and by Clear list — clearing while the watcher runs would be undone
// instantly, since every mutation re-pushes the whole comment list.
async function stopWatch() {
  if (watching) await runAgent('stop')
  watching = false
  $('watchLabel').textContent = 'Auto-scan while I scroll'
  $('watch').classList.remove('on')
  document.body.classList.remove('watching')
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
  $('watchLabel').textContent = watching ? 'Auto-scan on — just scroll' : 'Auto-scan while I scroll'
  $('watch').classList.toggle('on', watching)
  document.body.classList.toggle('watching', watching)   // the pinwheel mark spins while watching
  renderCount(0)
}

// live results from the watcher as the user scrolls
chrome.runtime.onMessage.addListener((m, sender) => {
  if (m?.type !== 'knowella-commenters' || sender.tab?.id !== tabId) return
  // Moved to a different post with a list still open: the old post's lock would
  // silently reject every new commenter. Hold the push and tell the user.
  if (captured.length && postUrl && m.url && m.url !== postUrl) {
    msg('New post detected. Export or clear the current list to start capturing this one.', 'err')
    return
  }
  postUrl = m.url || postUrl
  const added = mergeFound(m.found)
  if (added > 0) { saveState(); renderCount(added) }
})

async function sendBatch(commenters, skipFilter) {
  const campaign = $('campaign').value
  if (!campaign) { msg('Pick a campaign first.', 'err'); return null }
  const r = await fetch(`${cfg.appUrl}/api/linkedin/capture`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Capture-Token': cfg.token },
    body: JSON.stringify({ campaign, post_url: postUrl, commenters, skip_filter: skipFilter }),
  })
  if (!r.ok) throw new Error((await r.text()).slice(0, 200))
  return r.json()
}

function resultLine(d, campaign) {
  return `Added ${d.added} lead${d.added === 1 ? '' : 's'} to ${campaign} — ${d.with_email} with email, ${d.no_email} without` +
    `${d.off_icp ? `, ${d.off_icp} skipped (didn’t match the campaign’s targeting)` : ''}` +
    `${d.duplicates ? `, ${d.duplicates} already captured` : ''}${d.suppressed ? `, ${d.suppressed} suppressed` : ''}` +
    `${d.credits_used ? ` · ${d.credits_used} Apollo credits` : ''}. Review them in the app.`
}

// never lose a skip silently: list who the filter dropped, with a ONE-CLICK rescue —
// "Add these anyway" re-sends exactly the skipped people with the filter bypassed.
function showSkipped(skipped, offIcp) {
  const list = $('list')
  list.hidden = false
  list.innerHTML = ''
  const head = document.createElement('div')
  head.style.cssText = 'color:var(--muted);font-style:italic'
  head.textContent = `skipped by the targeting filter (${offIcp}):`
  list.appendChild(head)
  for (const s of skipped) {
    const row = document.createElement('div')
    row.textContent = s.name
    const sp = document.createElement('span')
    sp.textContent = ` — ${s.headline}`
    row.appendChild(sp)
    list.appendChild(row)
  }
  const btn = document.createElement('button')
  btn.className = 'rescue'
  btn.textContent = `Add these ${skipped.length} anyway`
  btn.onclick = async () => {
    btn.disabled = true
    try {
      const d = await sendBatch(skipped.map((s) => ({ name: s.name, profile_url: s.profile_url, headline: s.headline })), true)
      if (d) {
        list.hidden = true
        list.innerHTML = ''
        msg(resultLine(d, $('campaign').value), 'ok')
      }
    } catch (e) {
      msg(`Could not add them: ${e.message}`, 'err')
      btn.disabled = false
    }
  }
  list.appendChild(btn)
}

// Local-only exit: download the captured list as CSV. Nothing is sent to the app,
// no campaign, no enrichment — for efforts whose leads must stay out of this system
// (e.g. a different brand). Enrich the CSV separately if needed.
function exportCsv() {
  if (!captured.length) return
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const rows = [['name', 'profile_url', 'headline', 'captured_from', 'captured_at']]
  for (const c of captured) rows.push([c.name, c.profile_url, c.headline, lockActivity || '', new Date().toISOString()])
  const blob = new Blob([rows.map((r) => r.map(esc).join(',')).join('\r\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `linkedin-capture-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
  msg(`Exported ${captured.length} to CSV (local only — nothing sent to the app).`, 'ok')
}

async function send() {
  $('send').disabled = true
  msg('Sending…')
  try {
    const d = await sendBatch(captured, false)
    if (!d) return
    captured = []
    await saveState()
    renderCount(0)
    msg(resultLine(d, $('campaign').value), 'ok')
    if (d.skipped?.length) showSkipped(d.skipped, d.off_icp)
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
  if (cfg.appUrl) $('appLink').href = cfg.appUrl   // the eyebrow opens the app

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
  $('export').onclick = exportCsv
  $('clear').onclick = async () => {
    await stopWatch()          // else the running observer re-pushes the same list instantly
    captured = []; lockActivity = ''; postUrl = ''; dismissed = new Set()
    await saveState()
    renderCount(0)
    msg('Cleared. Open the next post and Scan (or turn auto-scan back on).')
  }
}

init()
