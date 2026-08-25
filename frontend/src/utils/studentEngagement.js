const completedTaskStatuses = new Set(['completed', 'cancelled', 'canceled', 'closed'])

export const studentEngagementApi = Object.freeze({
  getContext: 'crm.api.student_context.get_student_context',
  requestLifecycleTransition: 'crm.api.student_lifecycle.request_transition',
})

/**
 * @typedef {{ stage?: string, target_stage?: string, label?: string, requires_evidence?: boolean, requires_reason?: boolean }} LifecycleTarget
 * @typedef {{ allowed_targets?: LifecycleTarget[], allowed_transitions?: LifecycleTarget[], current_stage?: string, stage?: string, revision?: number }} StudentLifecycleContext
 * @typedef {{ lifecycle?: StudentLifecycleContext, latest_interaction?: Record<string, unknown>, latest_outcome?: Record<string, unknown>, next_action?: Record<string, unknown>, history?: { items?: Record<string, unknown>[], next_cursor?: string } }} StudentEngagementContext
 * @typedef {{ event_id?: string, revision?: number, receipt?: string }} LifecycleTransitionResponse
 */

export function createStudentEngagementCommandId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function lifecycleTargets(lifecycle) {
  const targets = lifecycle?.allowed_targets || lifecycle?.allowed_transitions || []
  return targets
    .map((target) => ({
      label: target.label || target.stage || target.target_stage,
      value: target.stage || target.target_stage,
      requiresEvidence: Boolean(target.requires_evidence),
      requiresReason: Boolean(target.requires_reason),
    }))
    .filter((target) => target.value)
}

export function isLifecycleCommandAllowed({ target, reason, evidence, lifecycle }) {
  const config = lifecycleTargets(lifecycle).find((item) => item.value === target)
  if (!config) return false
  if (config.requiresReason && !String(reason || '').trim()) return false
  if (config.requiresEvidence && !splitEvidenceReferences(evidence).length) return false
  return true
}

export function buildLifecycleTransitionPayload({
  student,
  target,
  outcomeCode,
  reason,
  evidence,
  revision,
  idempotencyKey,
  correlationId,
}) {
  const payload = {
    student,
    target_stage: target,
    reason: String(reason || '').trim(),
    evidence_refs: splitEvidenceReferences(evidence),
    expected_revision: Number(revision),
    idempotency_key: idempotencyKey,
    correlation_id: correlationId,
  }
  if (outcomeCode) payload.outcome_code = outcomeCode
  return payload
}

export function isOverdueNextAction(action, now = new Date()) {
  const dueAt = action?.due_at || action?.due_date
  if (!dueAt || completedTaskStatuses.has(String(action?.status || '').toLowerCase())) return false
  const due = new Date(dueAt)
  return !Number.isNaN(due.getTime()) && due < now
}

export function formatStudentEngagementDate(value, locale = 'vi-VN') {
  if (!value) return __('Not scheduled')
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return __('Unavailable')
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

export function safeLifecycleError(error, fallback) {
  const status = error?.httpStatusCode || error?.status
  if ([401, 403].includes(status)) return __('You are not permitted to change this lifecycle.')
  if ([409, 412].includes(status)) return __('This lifecycle changed. Reload the Student and review the current state.')
  if (status === 422) return __('Please correct the transition details and try again.')
  return error?.messages?.[0] || error?.message || fallback
}

function splitEvidenceReferences(value) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean)
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean)
}
