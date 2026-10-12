import { useEffect, useRef } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import Icon from './Icon'

// The record panel every lead and company opens in (Sid's item 26), at the Knowella
// supply-chain module's size: 84vw wide (90vw on phones), full height less 16px, 8px
// from the top and right, 8px radius, sliding in from the right over 0.3s on a blurred
// dark backdrop. Escape or a click on the backdrop closes it; focus goes back to where
// it was.
export default function SlideOut({ open, onClose, label, children }) {
  const panel = useRef(null)
  const reduce = useReducedMotion()
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!open) return undefined
    const before = document.activeElement
    const onKey = (e) => { if (e.key === 'Escape') closeRef.current() }
    window.addEventListener('keydown', onKey)
    const t = setTimeout(() => panel.current?.focus(), 40)
    return () => {
      window.removeEventListener('keydown', onKey)
      clearTimeout(t)
      if (before && typeof before.focus === 'function') before.focus()
    }
  }, [open])
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div key="so-bg" className="so-backdrop" onClick={() => closeRef.current()}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }} />
          <motion.aside key="so-panel" ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={label}
            className="so-panel"
            initial={reduce ? { opacity: 0 } : { x: '104%' }} animate={reduce ? { opacity: 1 } : { x: 0 }}
            exit={reduce ? { opacity: 0 } : { x: '104%' }} transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}>
            <button className="icon-btn so-close" aria-label="Close" onClick={() => closeRef.current()}>
              <Icon name="x" size={18} />
            </button>
            {children}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
