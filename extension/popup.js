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
let lockModal = ''         // …and to that post's reactions modal ("All 117")
let otherPost = 0          // reactors skipped because they belong to a DIFFERENT post
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
  lockModal = s?.lockModal || ''
  dismissed = new Set(s?.dismissed || [])
  renderCount(0)
}
const saveState = () =>
  chrome.storage.session.set({ [sessionKey()]: { items: captured, postUrl, lock: lockActivity,
                                                 lockModal, dismissed: [...dismissed] } })

// merge a scrape result into the accumulated list; returns how many were new.
// The first batch with activity ids locks capture to that post (majority id), so
// scrolling past other feed posts never sweeps in their commenters.
function mergeFound(found) {
  if (!lockActivity) {
    const counts = {}
    for (const c of found || []) if (c.activity) counts[c.activity] = (counts[c.activity] || 0) + 1
    lockActivity = (Object.entries(counts).sort((a, b) => b[1] - a[1])[0] || [])[0] || ''
  }
  // reactions carry no post id, so lock to the first modal seen — otherwise opening
  // another post's reactors silently piles them onto this list
  if (!lockModal) lockModal = (found || []).find((c) => c.modal)?.modal || ''
  const known = new Set(captured.map((c) => norm(c.profile_url)))
  let added = 0
  otherPost = 0
  for (const c of found || []) {
    if (lockActivity && c.activity && c.activity !== lockActivity) continue   // another post's comment
    if (c.source === 'reaction' && c.modal && lockModal && c.modal !== lockModal) {
      otherPost++                                                             // another post's reactors
      continue
    }
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

// action: optional {label, onClick} — puts the fix INSIDE the message, so a warning
// that tells you to do something doesn't also make you go hunting for the button
function msg(text, cls = '', action = null) {
  $('msg').innerHTML = ''
  if (!text) return
  const d = document.createElement('div')
  d.className = `msg ${cls}`
  d.textContent = text
  if (action) {
    const b = document.createElement('button')
    b.className = 'msg-action'
    b.textContent = action.label
    b.onclick = action.onClick
    d.appendChild(b)
  }
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

    // REACTIONS: LinkedIn lists reactors in a modal ("All 117") — far more numerous
    // than commenters (4 comments vs 117 reactions on the same post) and still a
    // self-selected signal, just weaker intent.
    //
    // Live-verified 2026-08-06 against the obfuscated build: every reactor row carries
    // ONE aria-label with everything —
    //   "Shilesh Gargi reacted with Funny, 3rd+ degree connection, Head of Marketing | ..."
    // That beats walking the DOM, whose wrappers use display:contents (no box at all,
    // so geometry- and class-based detection both fail). The modal only ever belongs
    // to the post it was opened from, so no activity id is needed to scope it.
    // The modal carries no post id, so identify it by its own "All 117" tab count —
    // stable for a given post, and enough to notice you've opened a DIFFERENT post's
    // reactors (otherwise every post's list silently piles onto the last one).
    const reactionRows = document.querySelectorAll('[aria-label*="reacted with"]')
    // computed ONLY when a reactions modal is actually open: reading innerText forces
    // layout, and this used to run over every anchor on the page every 700ms while
    // auto-scan was on, whether or not any reactions existed
    let modalKey = ''
    if (reactionRows.length) {
      for (const e of document.querySelectorAll('[role="tab"], button')) {
        const t = clean(e.innerText || '')
        if (/^all\s+[\d,]+$/i.test(t)) { modalKey = t; break }
      }
    }
    const seenHref = new Set(items.map((i) => i.profile_url))
    for (const el of reactionRows) {
      const a = el.closest('a[href*="/in/"]') || el.querySelector('a[href*="/in/"]')
      if (!a) continue
      const href = (a.href || '').split('?')[0].split('#')[0]
      if (!href.includes('/in/') || seenHref.has(href)) continue
      const label = el.getAttribute('aria-label') || ''
      // name ... "reacted with X," ... optional "Nth degree connection," ... headline
      const m = label.match(/^(.*?)\s+reacted with\s+[^,]*,\s*(?:[^,]*degree connection,\s*)?([\s\S]*)$/i)
      const name = cleanName(m ? m[1] : (a.innerText || '').split('\n')[0] || '')
      if (!name) continue
      let headline = clean(m ? m[2] : '')
      if (!headline) {   // fall back to the row's own text
        const lines = (a.innerText || '').split('\n').map(clean).filter(Boolean)
        headline = lines.slice(1).find((l) => l.length > 6 && !badgeRe.test(l) && cleanName(l) !== name) || ''
      }
      seenHref.add(href)
      items.push({ name, profile_url: href, headline, activity: '', source: 'reaction', modal: modalKey })
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
      let misses = 0
      const push = () => {
        // The panel is the only consumer. If it's closed, sending throws — after a few
        // of those, disconnect: an observer left running on LinkedIn's DOM forever is
        // both wasted work and an artifact we don't want lingering.
        try {
          chrome.runtime.sendMessage({ type: 'knowella-commenters',
            url: location.href.split('?')[0], found: scrape() },
            () => { if (chrome.runtime.lastError) bumpMiss(); else misses = 0 })
        } catch (e) { bumpMiss() }
      }
      const bumpMiss = () => {
        if (++misses >= 3 && window.__knowellaWatch) {
          window.__knowellaWatch.disconnect()
          window.__knowellaWatch = null
        }
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
  if (otherPost > 0) {
    // the guard that stops one post's reactors piling onto another's list
    msg(`Different post — ${otherPost} reactors not added. Your list still holds ${captured.length} from the first post.`,
        'err', { label: 'Start fresh here', onClick: () => clearAll(true) })
    return
  }
  // say what came from where — so "it's not capturing" is never a guess again
  if (res.counts) {
    const c = res.counts
    msg(`Scanned: ${c.total} on the page (${c.reactions} from the reactions list, ${c.total - c.reactions} from comments) → ${added} new.`)
  }
}

// Wipe the list and every lock. Deliberately NOT automatic on navigation: silently
// discarding 117 captured people because you scrolled into another post is
// unrecoverable. Instead the cross-post warnings offer this as a one-click action.
// keepWatching: re-arm auto-scan afterwards so a fresh post starts capturing at once.
async function clearAll(keepWatching = false) {
  const wasWatching = watching
  await stopWatch()          // else the running observer re-pushes the old list instantly
  captured = []; lockActivity = ''; lockModal = ''; postUrl = ''; otherPost = 0; dismissed = new Set()
  await saveState()
  renderCount(0)
  if (keepWatching && wasWatching) {
    await toggleWatch()      // resumes on the post you're now looking at
    msg('Fresh list — auto-scan is back on for this post. Just scroll.')
  } else {
    msg('Cleared. Open the next post and Scan (or turn auto-scan back on).')
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
    msg(`New post — the current list still holds ${captured.length} from the last one.`,
        'err', { label: 'Start fresh here', onClick: () => clearAll(true) })
    return
  }
  postUrl = m.url || postUrl
  const added = mergeFound(m.found)
  // persist FIRST — returning early on a cross-post warning used to drop people
  // mergeFound had already accepted (in memory, never saved, lost on reload)
  if (added > 0) { saveState(); renderCount(added) }
  if (otherPost > 0) {
    // auto-scan hit another post's reactors — say so instead of silently dropping them
    msg(`Different post — ${otherPost} reactors not added. “Clear list” to capture this one.`, 'err')
  }
})

// The API caps a capture at 200 people, but the panel can accumulate far more
// (117 reactors on one post, 228 across two) — so send in chunks and add the
// results up. Without this, any capture over 200 failed outright at Send.
const CHUNK = 150

async function sendBatch(commenters, skipFilter) {
  const campaign = $('campaign').value
  if (!campaign) { msg('Pick a campaign first.', 'err'); return null }
  const totals = { added: 0, with_email: 0, no_email: 0, off_icp: 0, duplicates: 0,
                   suppressed: 0, credits_used: 0, received: 0, skipped: [] }
  for (let i = 0; i < commenters.length; i += CHUNK) {
    const slice = commenters.slice(i, i + CHUNK)
    if (commenters.length > CHUNK) {
      msg(`Sending ${Math.min(i + CHUNK, commenters.length)}/${commenters.length}…`)
    }
    const r = await fetch(`${cfg.appUrl}/api/linkedin/capture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Capture-Token': cfg.token },
      body: JSON.stringify({ campaign, post_url: postUrl, commenters: slice, skip_filter: skipFilter }),
    })
    if (!r.ok) {
      const detail = (await r.text()).slice(0, 200)
      if (totals.added) throw new Error(`${detail} (${totals.added} already added before this failed)`)
      throw new Error(detail)
    }
    const d = await r.json()
    for (const k of ['added', 'with_email', 'no_email', 'off_icp', 'duplicates', 'suppressed', 'credits_used', 'received']) {
      totals[k] += d[k] || 0
    }
    if (d.skipped?.length) totals.skipped.push(...d.skipped)
  }
  return totals
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
  // attribute to whatever identifies the source: the post's activity id, else the
  // reactions modal it came from, else the page URL (was blank for reaction-only runs)
  const from = lockActivity || lockModal || postUrl || ''
  const at = new Date().toISOString()
  for (const c of captured) rows.push([c.name, c.profile_url, c.headline, from, at])
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
  // show the version — the only way to tell at a glance whether a reload took effect
  const v = chrome.runtime.getManifest().version
  const h1 = document.querySelector('.top h1')
  if (h1) h1.insertAdjacentHTML('beforeend', ` <span class="ver">v${v}</span>`)

  const tab = await activeTab()
  if (tab) { tabId = tab.id; await loadState() }

  $('gear').onclick = () => document.body.classList.toggle('setup')
  $('save').onclick = async () => {
    cfg = { appUrl: $('appUrl').value.trim().replace(/\/$/, ''), token: $('token').value.trim() }
    await chrome.storage.local.set(cfg)
    document.body.classList.remove('setup')
    await loadCampaigns()
  }
  // refresh campaigns when the panel regains focus — a campaign created in the app
  // while the panel sat open used to stay missing from the dropdown until reopen
  window.addEventListener('focus', () => { if (cfg.appUrl && cfg.token) loadCampaigns() })
  $('scan').onclick = scan
  $('watch').onclick = toggleWatch
  $('send').onclick = send
  $('export').onclick = exportCsv
  $('clear').onclick = () => clearAll(false)
}

init()
