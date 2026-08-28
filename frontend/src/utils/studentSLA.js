const staleCodes = new Set(['STALE_REVISION', 'STALE_OWNERSHIP_REVISION', 'LEASE_LOST'])

export function createStudentSLACommandId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function slaStatusPresentation(status) {
  const normalized = String(status || '').toLowerCase()
  const labels = {
    open: __('Open'),
    paused: __('Paused'),
    warned: __('Warning sent'),
    breached: __('Breached'),
    escalated: __('Escalated'),
    responded: __('Response recorded'),
    closed: __('Closed'),
    closed_inactive: __('Closed inactive'),
    superseded: __('Superseded'),
  }
  const themes = {
    open: 'blue',
    paused: 'orange',
    warned: 'orange',
    breached: 'red',
    escalated: 'red',
    responded: 'green',
    closed: 'green',
    closed_inactive: 'gray',
    superseded: 'gray',
  }
  return { label: labels[normalized] || status || __('Unavailable'), theme: themes[normalized] || 'gray' }
}

export function formatStudentSLADate(value, locale = 'vi-VN') {
  if (!value) return __('Not scheduled')
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return __('Unavailable')
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function buildPauseSLAPayload({ attempt, reasonCode, revision }) {
  return {
    attempt,
    reason_code: String(reasonCode || '').trim(),
    expected_revision: Number(revision),
  }
}

export function buildResumeSLAPayload({ attempt, revision }) {
  return { attempt, expected_revision: Number(revision) }
}

export function isStaleStudentSLAError(error) {
  const text = [error?.exc_type, error?.message, ...(error?.messages || [])]
    .filter(Boolean)
    .join(' ')
  return [...staleCodes].some((code) => text.includes(code)) || [409, 412].includes(error?.httpStatusCode || error?.status)
}

export function safeStudentSLAError(error, fallback) {
  const status = error?.httpStatusCode || error?.status
  if ([401, 403].includes(status)) return __('You are not permitted to perform this action.')
  if ([409, 412].includes(status)) return __('This SLA changed. Reload it and review the current state.')
  if (status === 422) return __('Please correct the selected reason and try again.')
  return error?.messages?.[0] || error?.message || fallback
}
