/**
 * Classify a frappe-ui resource without replacing stale content during a
 * background refresh.
 *
 * `fetched` is the authoritative signal that a request completed. A resource
 * can legitimately contain an empty array or object, so callers should only
 * override `hasData` when `null` is a meaningful value for their resource.
 */
export function getResourceViewState(resource, options = {}) {
  const hasData =
    options.hasData !== undefined
      ? Boolean(options.hasData)
      : resource?.data !== null && resource?.data !== undefined

  if (resource?.error && !hasData) return 'error'
  if (!resource?.fetched && !hasData) return 'loading'
  return 'ready'
}
