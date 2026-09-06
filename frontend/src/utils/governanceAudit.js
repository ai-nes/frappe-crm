export const governanceAuditApi = Object.freeze({
  checkImpact: 'crm.fcrm.master_data_governance.check_impact',
  proposeChange: 'crm.fcrm.master_data_governance.propose_change',
  approveChange: 'crm.fcrm.master_data_governance.approve_change',
  rejectChange: 'crm.fcrm.master_data_governance.reject_change',
  getPendingChange: 'crm.fcrm.master_data_governance.get_pending_change',
  listPendingChanges: 'crm.fcrm.master_data_governance.list_pending_changes',
  proposeAdditiveValue: 'crm.fcrm.master_data_governance.propose_additive_value',
  createAdditiveValue: 'crm.fcrm.master_data_governance.create_additive_value',
  getTimeline: 'crm.api.critical_transition_audit.get_critical_transition_timeline',
})

export const governedDoctypes = Object.freeze({
  'CRM Lead Source': { ownerRole: 'Marketing', approverRoles: ['Marketing'] },
  'CRM Platform': { ownerRole: 'Marketing', approverRoles: ['Marketing'] },
  'CRM Campus': { ownerRole: 'Admissions Director', approverRoles: ['Admissions Director'] },
})

export function createGovernanceCommandId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function isGovernedDoctype(doctype) {
  return Boolean(governedDoctypes[doctype])
}

export function buildProposalPayload({ doctype, docname, action, newValue, reason, idempotencyKey, correlationId, expectedVersion }) {
  return {
    doctype: String(doctype || '').trim(),
    docname: String(docname || '').trim(),
    action,
    new_value: ['Rename', 'Supersede'].includes(action) ? String(newValue || '').trim() : null,
    reason: String(reason || '').trim(),
    idempotency_key: idempotencyKey,
    correlation_id: correlationId || idempotencyKey,
    expected_version: Number.isFinite(Number(expectedVersion)) ? Number(expectedVersion) : null,
  }
}

export function buildAdditiveValuePayload({ doctype, value, reason, idempotencyKey, correlationId, leadSource, category }) {
  return {
    doctype: String(doctype || '').trim(),
    value: String(value || '').trim(),
    reason: String(reason || '').trim() || null,
    idempotency_key: idempotencyKey,
    correlation_id: correlationId || idempotencyKey,
    ...(leadSource ? { lead_source: leadSource } : {}),
    ...(category ? { category } : {}),
  }
}

export function governanceAffordances(user, doctype) {
  const profileRoles = {
    marketing: 'Marketing',
    lead_sales: 'Lead Sales',
    admissions_director: 'Admissions Director',
  }
  const roles = new Set([
    ...(user?.roles || user?.crm_roles || []),
    profileRoles[user?.crm_profile],
  ].filter(Boolean))
  const policy = governedDoctypes[doctype]
  if (!policy) return { canPropose: false, canApprove: false, ownerRole: null, approverRoles: [] }
  return {
    canPropose: roles.has(policy.ownerRole),
    canApprove: policy.approverRoles.some((role) => roles.has(role)),
    ownerRole: policy.ownerRole,
    approverRoles: policy.approverRoles,
  }
}

export function normalizeImpact(dto = {}) {
  const entries = Object.entries(dto.impact || dto.usage || dto || {})
    .filter(([, count]) => Number.isFinite(Number(count)))
    .map(([reference, count]) => ({ reference, count: Number(count) }))
  return { entries, total: entries.reduce((total, item) => total + item.count, 0) }
}

export function normalizeChange(dto = {}) {
  return {
    name: dto.name || dto.change_log_name || dto.change || '',
    status: dto.status || 'Proposed',
    action: dto.action || '',
    reason: dto.reason || '',
    oldValue: dto.old_value || dto.reference_docname || '',
    newValue: dto.new_value || '',
    requiredApproverRoles: String(dto.required_approver_roles || '')
      .split(',').map((role) => role.trim()).filter(Boolean),
    approvedRoles: String(dto.approved_by_roles || '')
      .split(',').map((role) => role.trim()).filter(Boolean),
    version: dto.version ?? null,
  }
}

export function normalizeTimeline(dto = {}) {
  const timeline = dto.timeline || dto.items || []
  return {
    items: timeline.map((item) => ({
      id: item.event_id || item.name || item.id || '',
      eventType: item.event_type || __('Admission event'),
      occurredAt: item.occurred_at || item.timestamp || null,
      actor: item.actor || __('System'),
      transition: item.transition || [item.from_value, item.to_value].filter(Boolean).join(' → ') || null,
      reason: item.reason_redacted ? __('Reason restricted') : item.reason || null,
      redacted: Boolean(item.reason_redacted || item.redacted),
      correlationId: item.correlation_id || null,
    })),
    nextCursor: dto.next_cursor || dto.cursor || null,
    completeness: dto.completeness || null,
  }
}

export function governanceErrorState(error) {
  const status = error?.httpStatusCode || error?.status
  const code = error?.error_code || error?.exc_type
  if ([401, 403].includes(status)) return { kind: 'denied', retryable: false, message: __('You are not permitted to perform this governance action.') }
  if ([409, 412].includes(status) || ['STALE_VERSION', 'CONFLICT'].includes(code)) return { kind: 'conflict', retryable: true, message: __('This record changed. Reload the current version and try again.') }
  if (code === 'FEATURE_DISABLED') return { kind: 'disabled', retryable: false, message: __('Governance is not enabled in this environment.') }
  return { kind: 'retry', retryable: true, message: error?.messages?.[0] || error?.message || __('The request could not be completed. Try again.') }
}
