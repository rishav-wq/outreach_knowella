// Monogram avatars in the main app's style: a soft pastel tint with initials in
// the same hue (never a solid saturated disc, never white text). One shared
// helper so Leads, Inbox, Library and the drawer all render the same person the
// same way — color is stable per name.
export const initials = (name) => {
  const p = (name || '').trim().split(/\s+/).filter(Boolean)
  if (!p.length) return '?'
  return (p[0][0] + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase()
}

// [background tint, initial ink] — drawn from the product's own tints
// (lavender pill, success mint, petal green/yellow, info blue).
const TINTS = [
  ['#e2e0ff', '#6e63ff'],
  ['#04b49229', '#04806b'],
  ['#e5f6de', '#3e8a2e'],
  ['#fff3c4', '#8a6d00'],
  ['#e2e8ff', '#2e5bff'],
]

export const avatarTint = (name) => {
  let h = 0
  for (let i = 0; i < (name || '').length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  const [background, color] = TINTS[h % TINTS.length]
  return { background, color }
}
