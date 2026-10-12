// What the campaign rules (src/enroll.py) refused, in words. Every way of adding
// people to a campaign reports refusals as {code: count}; this turns that into one
// sentence for the message after an import.
const LABEL = {
  running: 'already in another running campaign',
  cooling: 'emailed in the last 90 days (cooling off)',
  owned: 'another rep’s leads',
  company_cap: 'over the 2-per-company limit',
  customer: 'at existing Knowella customers',
}

export function refusedText(refused) {
  const parts = Object.entries(refused || {}).filter(([, n]) => n > 0)
  if (!parts.length) return ''
  const total = parts.reduce((a, [, n]) => a + n, 0)
  return ` Skipped ${total} by the campaign rules: ${parts.map(([k, n]) => `${n} ${LABEL[k] || k}`).join(', ')}.`
}
