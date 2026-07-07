import { useEffect } from 'react'
import { animate, motion, useMotionValue, useTransform } from 'framer-motion'

// Counts up to `value` smoothly whenever it changes.
export default function AnimatedNumber({ value = 0, duration = 0.7 }) {
  const mv = useMotionValue(0)
  const text = useTransform(mv, (v) => Math.round(v).toLocaleString())
  useEffect(() => {
    const controls = animate(mv, value || 0, { duration, ease: 'easeOut' })
    return () => controls.stop()
  }, [value, duration])
  return <motion.span>{text}</motion.span>
}
