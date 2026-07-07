// Shared Framer Motion variants — subtle + calm (minimal aesthetic).
const EASE = [0.22, 1, 0.36, 1] // easeOutExpo-ish

export const fadeUp = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.26, ease: EASE } },
}

export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.035, delayChildren: 0.02 } },
}

export const pageTransition = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.2, ease: EASE },
}

// No hover-bounce in a minimal UI — just a faint press.
export const tap = { whileTap: { scale: 0.99 } }
