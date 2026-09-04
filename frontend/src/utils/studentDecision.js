const terminalActionStatuses = new Set(['completed', 'failed', 'cancelled', 'canceled'])

// Kept in one place so the work surfaces can move with the versioned API
// without spreading endpoint names and wire-format assumptions through views.
export const studentDecisionApi = Object.freeze({
  // Immutable AI recommendations awaiting human review. The per-user worklist
  // read model is owned by `crm.api.student_worklist`; it projects
  // `CRM Recommendation` rows, never pending Action Items.
  listRecommendations: 'crm.api.student_worklist.list_student_worklist',
  createAction: 'crm.api.student_decision.create_action',
  // Accepted / manual-origin NBA Tasks only.
  listActions: 'crm.api.student_worklist.list_my_actions',
  // Append-only HITL decision on one recommendation. ACCEPT / ACCEPT_WITH_CHANGES
  // create exactly one NBA Task; REJECT / DEFER / DISMISS create none.
  decideRecommendation: 'crm.api.student_decision.decide_recommendation',
  transitionAction: 'crm.api.student_decision.transition_action',
  getContext: 'crm.api.student_context.get_student_context',
})

export function createStudentDecisionCommandId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/**
 * Normalize one immutable AI recommendation for the review queue.
 *
 * Accepts both the per-user worklist shape and the director read model
 * (`get_director_recommendations`: id, rank, recommendationKey, studentId,
 * actionId, aiPayload, evaluation, generatedAt). The `aiPayload` kernel object
 * is surfaced verbatim and never rewritten — it is the human-in-the-loop
 * proposal, not a work item.
 */
export function recommendationItem(dto = {}) {
  const aiPayload = dto.aiPayload && typeof dto.aiPayload === 'object'
    ? dto.aiPayload
    : (dto.ai_payload && typeof dto.ai_payload === 'object' ? dto.ai_payload : {})
  const evaluation = dto.evaluation && typeof dto.evaluation === 'object' ? dto.evaluation : {}
  const id = dto.id || dto.recommendation || dto.name || ''
  return {
    id,
    // Retained wire-compat alias; both identify the same CRM Recommendation.
    recommendation: id,
    rank: Number.isFinite(dto.rank) ? dto.rank : (parseInt(dto.rank, 10) || null),
    recommendationKey: dto.recommendationKey || dto.recommendation_key || null,
    student: dto.studentId || dto.student || dto.student_id || '',
    studentName: dto.studentName || dto.student_name || dto.student_label || dto.student || __('Student unavailable'),
    actionId: dto.actionId || dto.action_id || null,
    priority: dto.priority || 'low',
    action: aiPayload.actionType || aiPayload.action || dto.action || dto.recommended_action || dto.action_type || __('Recommended action'),
    timing: aiPayload.timing || dto.timing || dto.recommended_timing || null,
    channel: aiPayload.channel || dto.channel || null,
    reason: aiPayload.objective || dto.reason || dto.rationale || '',
    aiPayload,
    evaluation: {
      id: evaluation.id || null,
      disposition: evaluation.disposition || null,
      status: evaluation.status || null,
    },
    generatedAt: dto.generatedAt || dto.generated_at || dto.recommended_at || null,
    // CAS guard for the append-only decision. TODO(student_worklist): the
    // director analytics read model omits this; the per-user worklist read
    // model must expose `expected_revision` (or `modified`) so ACCEPT can guard.
    expectedRevision: dto.expected_revision ?? dto.expectedRevision ?? dto.revision ?? dto.source_revision ?? dto.modified ?? '',
    revision: String(dto.revision ?? dto.source_revision ?? dto.modified ?? ''),
    permittedDecisions: dto.permitted_decisions || dto.allowed_decisions || ['accepted', 'deferred', 'rejected', 'dismissed'],
    permittedExecutors: dto.permitted_executors || dto.allowed_assignees || [],
  }
}

export function actionItem(dto = {}) {
  const status = dto.execution_status || dto.status || 'planned'
  const dueAt = dto.due_at || dto.due_date || null
  return {
    name: dto.name || dto.action_id || '',
    student: dto.student || dto.student_id || '',
    studentName: dto.student_name || dto.student_label || dto.student || __('Student unavailable'),
    action: dto.action || dto.action_code || '',
    actionType: dto.action_type || __('Action'),
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

export const admissionsOutcomeMap = {
  NO_RESPONSE: 'Không nghe máy / Chưa kết nối',
  INTEREST_INCREASED: 'Quan tâm cao / Muốn đăng ký xét tuyển',
  NEEDS_MORE_INFORMATION: 'Cần gửi thêm thông tin ngành & học phí',
  CALL_BACK_LATER: 'Hẹn gọi lại sau',
  APPLICATION_STARTED: 'Bắt đầu nộp hồ sơ xét tuyển',
  APPLICATION_COMPLETED: 'Đã hoàn tất hồ sơ xét tuyển',
  NOT_INTERESTED: 'Không có nhu cầu xét tuyển',
}

export const admissionsActionStatusMap = {
  planned: 'Đã lên lịch',
  in_progress: 'Đang tư vấn',
  completed: 'Đã hoàn thành',
  failed: 'Không thành công',
  cancelled: 'Đã hủy',
  canceled: 'Đã hủy',
}

export function formatOutcomeLabel(outcome) {
  if (!outcome) return ''
  return __(admissionsOutcomeMap[outcome] || outcome)
}

export function formatActionStatusLabel(status) {
  if (!status) return ''
  return __(admissionsActionStatusMap[status] || status)
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

export function toUtcInstant(value) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toISOString()
}

export function buildActionTransitionPayload({ action, status, outcomeCode, evidence, reason, linkedInteraction, idempotencyKey, correlationId }) {
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
