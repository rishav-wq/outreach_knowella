import { useEffect, useRef, useState } from 'react'
import * as api from '../api'
import Skeleton from './Skeleton'
import { useMe, isAdmin } from '../me'

// The BDR playbook, Sid's single HTML file, running inside the app.
//
// It runs in a SANDBOXED frame (scripts only, no same-origin), so its own script
// can't read this page, the session or the API. The server swaps the file's browser
// storage for an in-frame store pre-filled with this person's progress (src/training.py).
// When the frame has loaded, this page hands it one end of a private MessageChannel;
// each save and each Target board read or write comes back over it, and this page makes
// the API call with the user's session. The server checks everything again: a save
// needs the right version, a board change has to pass the claim rules.

const SAVE_DELAY_MS = 400            // a burst of ticks becomes one save
const RETRY_MS = [2000, 5000, 10000, 30000]
const BOARD_POLL_MS = 15000          // how fresh other people's claims are
const SEG_ID = /^[a-z0-9]{1,24}__[a-z0-9]{1,32}$/

// One saver for the whole session, outside the component. A save still on its way
// when you leave the tab has to land before the playbook is loaded again; otherwise
// the reloaded page starts from the older copy and its next save looks like a clash.
const saver = {
  versions: {},       // key -> the version the server holds
  keys: new Set(),    // the keys this playbook may save
  pending: {},        // key -> newest value not yet sent
  timers: {},
  inflight: {},       // key -> promise of the save on its way
  tries: {},
  clash: false,       // saved from another tab or device since this page loaded
  failed: '',         // a save the server refused for good (shown, not retried)
  listeners: new Set(),
  status() {
    if (this.clash) return 'clash'
    if (this.failed) return 'failed'
    if (Object.keys(this.timers).some((k) => this.tries[k])) return 'retry'
    if (Object.keys(this.pending).length || Object.keys(this.inflight).length) return 'saving'
    return 'saved'
  },
  emit() { const s = this.status(); this.listeners.forEach((fn) => fn(s)) },
  reset(versions, keys) {
    Object.values(this.timers).forEach(clearTimeout)
    Object.assign(this, { versions: { ...versions }, keys: new Set(keys), pending: {}, timers: {},
      tries: {}, clash: false, failed: '' })
    this.emit()
  },
  queue(key, value) {
    if (!this.keys.has(key) || this.clash) return
    this.pending[key] = value
    clearTimeout(this.timers[key])
    this.timers[key] = setTimeout(() => { delete this.timers[key]; this.flush(key) }, SAVE_DELAY_MS)
    this.emit()
  },
  flush(key) {
    if (this.inflight[key]) return this.inflight[key]
    if (!(key in this.pending) || this.clash) return Promise.resolve()
    const value = this.pending[key]
    delete this.pending[key]
    this.inflight[key] = (async () => {
      try {
        const r = await api.saveTrainingState(key, value, this.versions[key] || 0)
        this.versions[key] = r.version
        this.tries[key] = 0
      } catch (e) {
        if (!(key in this.pending)) this.pending[key] = value   // keep it unless a newer one came
        if (e.status === 409) {
          this.clash = true
        } else if (e.status === 400 || e.status === 413) {
          delete this.pending[key]
          this.failed = api.errorText(e)
        } else {                                                 // offline, server busy, session refresh
          const n = this.tries[key] = (this.tries[key] || 0) + 1
          clearTimeout(this.timers[key])
          this.timers[key] = setTimeout(() => { delete this.timers[key]; this.flush(key) },
            RETRY_MS[Math.min(n - 1, RETRY_MS.length - 1)])
        }
      } finally {
        delete this.inflight[key]
      }
      if (key in this.pending && !this.timers[key] && !this.clash) await this.flush(key)
    })().finally(() => this.emit())
    this.emit()
    return this.inflight[key]
  },
  // Send everything now and wait for it: before loading the page, and on leaving.
  idle() {
    Object.keys(this.timers).forEach((k) => { clearTimeout(this.timers[k]); delete this.timers[k] })
    Object.keys(this.pending).forEach((k) => this.flush(k))
    return Promise.all(Object.values(this.inflight)).catch(() => {})
  },
}

const STATUS_TEXT = {
  saved: 'Progress saved to your account',
  saving: 'Saving…',
  retry: 'Not saved yet. Retrying…',
  clash: 'Paused: opened somewhere else',
  failed: 'A change could not be saved',
}

export default function Training({ onNavigate }) {
  const me = useMe()
  const frameRef = useRef(null)
  const live = useRef({ loads: 0, away: false, subscribed: false, port: null })
  const handler = useRef(null)                // handles one message from the frame's port
  const [page, setPage] = useState(null)      // { src, content } once loaded
  const [error, setError] = useState('')      // load failure (text) or 'none' (nothing uploaded)
  const [status, setStatus] = useState(saver.status())
  const [away, setAway] = useState(false)     // the frame navigated off the playbook
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const fn = (s) => setStatus(s)
    saver.listeners.add(fn)
    return () => saver.listeners.delete(fn)
  }, [])

  // Load: finish any save still on its way, then fetch the page with this user's progress.
  useEffect(() => {
    let url = ''
    let cancelled = false
    live.current.port?.close()
    live.current = { loads: 0, away: false, subscribed: false, port: null }
    setAway(false); setPage(null); setError('')
    ;(async () => {
      // A change that couldn't be sent yet would be dropped by the reload below.
      for (let i = 0; i < 3 && (Object.keys(saver.pending).length || Object.keys(saver.inflight).length); i++) {
        await saver.idle()
      }
      try {
        const r = await api.getTrainingPage()
        if (cancelled) return
        saver.reset(r.versions || {}, r.content?.state_keys || [])
        url = URL.createObjectURL(new Blob([r.html], { type: 'text/html' }))
        setPage({ src: url, content: r.content || {} })
      } catch (e) {
        if (!cancelled) setError(e.status === 404 ? 'none' : api.errorText(e))
      }
    })()
    return () => {
      cancelled = true
      saver.idle()
      live.current.port?.close()
      if (url) URL.revokeObjectURL(url)
    }
  }, [reloadKey])

  // Unsaved progress: ask before the browser tab closes.
  useEffect(() => {
    const onLeave = (e) => {
      if (['saving', 'retry'].includes(saver.status())) { e.preventDefault(); e.returnValue = '' }
    }
    window.addEventListener('beforeunload', onLeave)
    return () => window.removeEventListener('beforeunload', onLeave)
  }, [])

  // Messages from the frame (over its private port): progress saves and the Target
  // board's calls. Replies and board snapshots go back the same way.
  useEffect(() => {
    const toFrame = (msg) => { if (!live.current.away) live.current.port?.postMessage(msg) }
    const pushBoard = async () => {
      try {
        const snap = await api.getSegments()
        toFrame({ kn: 'board-snapshot', docs: snap.docs || {}, names: snap.names || {} })
      } catch { /* the next poll tries again */ }
    }
    const reply = (id, ok, payload) => toFrame({ kn: 'rpc-result', id, ok, ...payload })
    const rpc = async (m) => {
      const a = (m.args && typeof m.args === 'object') ? m.args : {}
      try {
        if (m.method === 'board.subscribe') {
          live.current.subscribed = true
          reply(m.id, true, { result: null })
          pushBoard()
        } else if (m.method === 'board.get') {
          if (!SEG_ID.test(String(a.id))) throw Object.assign(new Error('not a board row'), { code: 'not a board row' })
          const r = await api.getSegment(a.id)
          reply(m.id, true, { result: r.doc || null })
        } else if (m.method === 'board.set') {
          if (!SEG_ID.test(String(a.id))) throw Object.assign(new Error('not a board row'), { code: 'not a board row' })
          const n = (a.next && typeof a.next === 'object') ? a.next : {}
          const body = { status: typeof n.status === 'string' ? n.status : 'grey' }
          if (n.mtgs != null && Number.isFinite(Number(n.mtgs))) body.mtgs = Math.trunc(Number(n.mtgs))
          if (typeof n.note === 'string') body.note = n.note.slice(0, 300)
          if (typeof n.owner === 'string') body.owner = n.owner
          try {
            await api.putSegment(a.id, body)
            reply(m.id, true, { result: null })
          } finally {
            pushBoard()      // success or refusal, the page redraws from what the server holds
          }
        } else {
          throw Object.assign(new Error('not available here'), { code: 'not available here' })
        }
      } catch (e) {
        // The page shows `code` in its toast, so it carries the server's sentence.
        const text = e.code || (e.status ? api.errorText(e) : 'the shared board did not answer')
        reply(m.id, false, { error: text, code: text })
      }
    }
    handler.current = (m) => {
      if (!m || typeof m !== 'object' || live.current.away) return
      if (m.kn === 'save' && typeof m.key === 'string' && typeof m.value === 'string') saver.queue(m.key, m.value)
      else if (m.kn === 'rpc' && Number.isInteger(m.id) && typeof m.method === 'string') rpc(m)
    }
    const poll = setInterval(() => {
      if (live.current.subscribed && document.visibilityState === 'visible') pushBoard()
    }, BOARD_POLL_MS)
    const onVisible = () => { if (live.current.subscribed && document.visibilityState === 'visible') pushBoard() }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      handler.current = null
      clearInterval(poll)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  // First load: hand the playbook its private port. That is the only message ever
  // posted to the frame's window ('*' because a sandboxed frame has no origin to name),
  // and it goes to the document that just loaded. The playbook's links all open in a new
  // tab; if the frame ever loads a second document, it has left the playbook: close the
  // port (that page never had it) and offer a reload.
  const onFrameLoad = () => {
    const L = live.current
    L.loads += 1
    if (L.loads > 1) {
      L.away = true
      L.port?.close()
      L.port = null
      setAway(true)
      return
    }
    const ch = new MessageChannel()
    ch.port1.onmessage = (ev) => handler.current?.(ev.data)
    L.port = ch.port1
    frameRef.current?.contentWindow?.postMessage({ kn: 'init' }, '*', [ch.port2])
  }

  if (error === 'none') {
    return (
      <div className="empty">
        <h3>No playbook yet</h3>
        <p className="muted">
          {isAdmin(me)
            ? 'Upload the BDR playbook (the HTML file) on the Team page, and it appears here for everyone.'
            : 'An admin uploads the BDR playbook. It will appear here once they do.'}
        </p>
        {isAdmin(me) && onNavigate && (
          <div className="empty-actions"><button className="btn primary" onClick={() => onNavigate('Team')}>Go to Team</button></div>
        )}
      </div>
    )
  }
  if (error) {
    return (
      <div style={{ padding: 28 }}>
        <div className="banner error">Couldn’t load the playbook: {error}</div>
        <button className="btn" onClick={() => setReloadKey((k) => k + 1)}>Try again</button>
      </div>
    )
  }

  return (
    <div className="training">
      <div className="training-bar">
        <span className={`training-save s-${status}`} role="status" aria-live="polite">
          <span className="training-dot" />{STATUS_TEXT[status]}
        </span>
        {status === 'clash' && (
          <span className="training-note">
            The playbook was saved from another tab or device after this one opened.
            <button className="linklike" onClick={() => setReloadKey((k) => k + 1)}>Reload to continue</button>
          </span>
        )}
        {status === 'failed' && <span className="training-note">{saver.failed}</span>}
        {away && (
          <span className="training-note">
            The frame left the playbook.
            <button className="linklike" onClick={() => setReloadKey((k) => k + 1)}>Reload the playbook</button>
          </span>
        )}
        {page?.content?.uploaded_at && (
          <span className="training-ver" title={`Version ${page.content.id || ''}`}>
            Updated {new Date(page.content.uploaded_at).toLocaleDateString()}
          </span>
        )}
      </div>
      {page ? (
        <iframe
          key={page.src}
          ref={frameRef}
          className="training-frame"
          title="BDR training playbook"
          src={page.src}
          onLoad={onFrameLoad}
          // Scripts run, but in an opaque origin: no access to this page, its storage or
          // its session. Links open in a normal new tab; copy buttons may use the clipboard.
          sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
          allow="clipboard-write"
          referrerPolicy="no-referrer"
        />
      ) : (
        <div style={{ padding: 28 }}><Skeleton h={22} w="40%" /><Skeleton h={380} r={12} style={{ marginTop: 16 }} /></div>
      )}
    </div>
  )
}
