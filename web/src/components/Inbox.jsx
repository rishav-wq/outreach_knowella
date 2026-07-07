import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import * as api from '../api'
import Icon from './Icon'
import Skeleton from './Skeleton'
import { fadeUp, stagger } from './anim'

const when = (ts) => {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  const days = (Date.now() - d.getTime()) / 86400000
  if (days < 1) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (days < 7) return d.toLocaleDateString([], { weekday: 'short' })
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

// Unified reply inbox — every incumbent converges on this pattern:
// thread list on the left, full conversation on the right.
export default function Inbox({ campaign }) {
  const [data, setData] = useState(null)
  const [sel, setSel] = useState(null)
  const [thread, setThread] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  const load = () => api.getInbox(campaign)
    .then((d) => { setData(d); if (d.items?.length && !sel) setSel(d.items[0].thread_id) })
    .catch(() => setData({ connected: false, items: [] }))
    .finally(() => setRefreshing(false))

  useEffect(() => { setData(null); setSel(null); setThread(null); load() }, [campaign])
  useEffect(() => {
    if (!sel) { setThread(null); return }
    setThread(null)
    api.getThread(campaign, sel).then(setThread).catch(() => setThread({ messages: [] }))
  }, [campaign, sel])

  if (!data) {
    return (
      <div className="inbox">
        <div className="inbox-list">
          {[0, 1, 2].map((i) => (
            <div className="inbox-skel" key={i}><Skeleton w="65%" h={13} /><Skeleton w="90%" h={11} style={{ marginTop: 8 }} /></div>
          ))}
        </div>
        <div className="inbox-thread"><Skeleton w="45%" h={16} /><Skeleton w="100%" h={80} r={8} style={{ marginTop: 16 }} /></div>
      </div>
    )
  }

  if (!data.connected) {
    return (
      <motion.div className="empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
        <div className="empty-icon"><Icon name="inbox" size={24} /></div>
        <h3>Connect Apollo to see replies</h3>
        <p className="muted">
          Replies land here once sending is wired up: set <code>APOLLO_API_KEY</code> in <code>.env</code> and
          the campaign&apos;s <code>sending.sequence_id</code> + <code>mailbox_id</code>, then restart the backend.
        </p>
        {data.error && <p className="muted" style={{ marginTop: 10 }}><code>{data.error.slice(0, 160)}</code></p>}
      </motion.div>
    )
  }

  if (data.items.length === 0) {
    return (
      <motion.div className="empty" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
        <div className="empty-icon"><Icon name="inbox" size={24} /></div>
        <h3>No replies yet</h3>
        <p className="muted">When a lead answers one of your sent emails, the conversation shows up here.</p>
        <div className="empty-actions">
          <button className="btn" onClick={() => { setRefreshing(true); load() }}>
            {refreshing ? <><span className="spinner spinner-dark" /> Checking…</> : 'Check again'}
          </button>
        </div>
      </motion.div>
    )
  }

  const current = data.items.find((i) => i.thread_id === sel)

  return (
    <div className="inbox">
      <div className="inbox-list">
        <div className="inbox-list-head">
          <span>{data.items.length} {data.items.length === 1 ? 'conversation' : 'conversations'}</span>
          <button className="icon-btn" title="Refresh" onClick={() => { setRefreshing(true); load() }}>
            <Icon name="refresh" size={14} className={refreshing ? 'spin' : ''} />
          </button>
        </div>
        <motion.div variants={stagger} initial="hidden" animate="show">
          {data.items.map((it) => (
            <motion.button key={it.thread_id} variants={fadeUp}
              className={`inbox-item ${it.thread_id === sel ? 'sel' : ''}`} onClick={() => setSel(it.thread_id)}>
              <div className="avatar sm">{(it.name || '?').slice(0, 1)}</div>
              <div className="inbox-item-main">
                <div className="inbox-item-top">
                  <span className="nm">{it.name}{it.unread && <span className="unread-dot" />}</span>
                  <span className="ts">{when(it.ts)}</span>
                </div>
                {it.company && <div className="inbox-item-sub">{it.company}</div>}
                <div className="inbox-item-snippet">{it.snippet || it.subject}</div>
              </div>
            </motion.button>
          ))}
        </motion.div>
      </div>

      <div className="inbox-thread">
        {!current ? <p className="muted">Select a conversation.</p> : !thread ? (
          <><Skeleton w="45%" h={16} /><Skeleton w="100%" h={80} r={8} style={{ marginTop: 16 }} /></>
        ) : (
          <>
            <div className="thread-head">
              <div>
                <div className="thread-name">{current.name}</div>
                <div className="thread-sub">{[current.company, current.lead_email].filter(Boolean).join(' · ')}</div>
              </div>
              <span className="thread-subject">{current.subject}</span>
            </div>
            <div className="thread-msgs">
              {thread.messages.map((m) => (
                <div key={m.id} className={`msg ${m.direction}`}>
                  <div className="msg-meta">{m.direction === 'in' ? current.name : 'You'} · {when(m.ts)}</div>
                  <pre className="msg-text">{m.text || '(no text body)'}</pre>
                </div>
              ))}
              {thread.messages.length === 0 && <p className="muted">Could not load this conversation{thread.error ? ` — ${thread.error.slice(0, 120)}` : '.'}</p>}
            </div>
            <p className="thread-note muted">Reply from your own mailbox — replies sent here would come from the rotation inbox, not you.</p>
          </>
        )}
      </div>
    </div>
  )
}
