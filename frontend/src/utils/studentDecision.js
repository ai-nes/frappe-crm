const terminalActionStatuses = new Set(['completed', 'failed', 'cancelled', 'canceled'])

// Kept in one place so the work surfaces can move with the versioned API
// without spreading endpoint names and wire-format assumptions through views.
export const studentDecisionApi = Object.freeze({
  listRecommendations: 'crm.api.student_worklist.list_student_worklist',
  listActions: 'crm.api.student_worklist.list_my_sales_actions',
  decideRecommendation: 'crm.api.student_decision.transition_recommendation',
  transitionAction: 'crm.api.student_decision.transition_sales_action',
  getContext: 'crm.api.student_context.get_student_context',
})

export function createStudentDecisionCommandId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function recommendationItem(dto = {}) {
  return {
    recommendation: dto.recommendation || dto.name || '',
    student: dto.student || dto.student_id || '',
    studentName: dto.student_name || dto.student_label || dto.student || __('Student unavailable'),
    priority: dto.priority || 'low',
    action: dto.action || dto.recommended_action || dto.action_type || __('Recommended action'),
    timing: dto.timing || dto.recommended_timing || null,
    reason: dto.reason || dto.rationale || '',
    revision: String(dto.revision ?? dto.source_revision ?? dto.modified ?? ''),
    permittedDecisions: dto.permitted_decisions || dto.allowed_decisions || ['accepted', 'deferred', 'rejected'],
    permittedExecutors: dto.permitted_executors || dto.allowed_assignees || [],
  }
}

export function salesActionItem(dto = {}) {
  const status = dto.execution_status || dto.status || 'planned'
  const dueAt = dto.due_at || dto.due_date || null
  return {
    name: dto.name || dto.sales_action || dto.action_id || '',
    student: dto.student || dto.student_id || '',
    studentName: dto.student_name || dto.student_label || dto.student || __('Student unavailable'),
    actionType: dto.action_type || dto.action || __('Sales action'),
    status,
    dueAt,
    overdue: Boolean(dto.overdue) || isActionOverdue({ status, dueAt }),
    assignee: dto.assignee_staff_label || dto.assignee_name || dto.assignee_staff || __('Unassigned'),
    revision: String(dto.revision ?? dto.source_revision ?? dto.modified ?? ''),
    permittedTransitions: dto.permitted_transitions || dto.allowed_transitions || [],
    outcomeCodes: dto.outcome_codes || dto.allowed_outcomes || [],
    linkedInteraction: dto.linked_interaction || dto.interaction || null,
    outcome: dto.outcome || dto.business_outcome || null,
  }
}

export function transitionOptions(action) {
  return (action?.permittedTransitions || [])
    .map((transition) => typeof transition === 'string'
      ? { value: transition, label: transition.replaceAll('_', ' ') }
      : { value: transition.status || transition.value || transition.to, label: transition.label || transition.status || transition.value || transition.to })
    .filter((transition) => transition.value)
}

export function isActionOverdue(action, now = new Date()) {
  if (!action?.dueAt || terminalActionStatuses.has(String(action.status || '').toLowerCase())) return false
  const due = new Date(action.dueAt)
  return !Number.isNaN(due.getTime()) && due < now
}

export function validateRecommendationDecision({ status, dueAt, deferKind, revisitAt, reason }) {
  if (status === 'accepted' && !dueAt) return __('A due time is required to accept this recommendation.')
  if (status === 'rejected' && !String(reason || '').trim()) return __('A rejection reason is required.')
  if (status === 'deferred' && deferKind === 'revisit' && !revisitAt) return __('Choose when this recommendation should return.')
  if (status === 'deferred' && deferKind === 'archive' && !String(reason || '').trim()) return __('An archival reason is required.')
  return ''
}

export function buildRecommendationDecisionPayload({ item, status, dueAt, assignee, deferKind, revisitAt, reason, idempotencyKey, correlationId }) {
  const payload = {
    name: item.recommendation,
    expected_revision: item.revision,
    status,
    decision_reason: String(reason || '').trim() || null,
    idempotency_key: idempotencyKey,
    correlation_id: correlationId,
  }
  if (status === 'accepted') {
    payload.due_at = toUtcInstant(dueAt)
    if (assignee) payload.assignee_staff = assignee
  }
  if (status === 'deferred') {
    payload.revisit_at = deferKind === 'revisit' ? toUtcInstant(revisitAt) : null
    payload.defer_kind = deferKind
  }
  return payload
}

export function toUtcInstant(value) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toISOString()
}

export function buildSalesActionTransitionPayload({ action, status, outcomeCode, evidence, reason, linkedInteraction, idempotencyKey, correlationId }) {
  const payload = {
    name: action.name,
    expected_revision: action.revision,
    status,
    reason: String(reason || '').trim() || null,
    evidence: String(evidence || '').trim() || null,
    linked_interaction: linkedInteraction || null,
    idempotency_key: idempotencyKey,
    correlation_id: correlationId,
  }
  if (outcomeCode) payload.outcome_code = outcomeCode
  return payload
}

export function safeStudentDecisionError(error, fallback) {
  const status = error?.httpStatusCode || error?.status
  if ([401, 403].includes(status)) return __('You are not permitted to complete this action.')
  if ([409, 412].includes(status)) return __('This work changed. Reload it and review the current state.')
  if (status === 422) return __('Please correct the details and try again.')
  return error?.messages?.[0] || error?.message || fallback
}
