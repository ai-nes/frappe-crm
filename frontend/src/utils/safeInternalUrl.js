/**
 * Accept provider links only when they are same-origin or HTTPS. In
 * particular, never pass javascript:, data:, or protocol-relative values into
 * an admin-facing href.
 */
export function safeInternalUrl(value) {
  if (typeof value !== 'string') return null
  const raw = value.trim()
  if (!raw || raw.startsWith('//')) return null

  const origin =
    typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin
      : 'http://localhost'

  try {
    const url = new URL(raw, origin)
    if (url.protocol === 'https:') return url.href
    if (url.origin === origin && url.protocol === 'http:') return url.href
  } catch {
    return null
  }

  return null
}
