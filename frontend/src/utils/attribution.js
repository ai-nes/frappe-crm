export const attributionApi = Object.freeze({
  getCampaign: 'crm.fcrm.student_attribution.get_campaign_attribution',
  getEvent: 'crm.fcrm.student_attribution.get_event_attribution',
  recordCampaignTouchpoint:
    'crm.fcrm.student_attribution.record_campaign_touchpoint',
  recordEventParticipation:
    'crm.fcrm.student_attribution.record_event_participation',
})

export function createAttributionCommandId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function attributionReadApi(kind) {
  return kind === 'event' ? attributionApi.getEvent : attributionApi.getCampaign
}

export function buildAttributionPayload({
  kind,
  record,
  student,
  contact,
  occurredAt,
  source,
  notes,
  status,
  idempotencyKey,
  correlationId,
  supersedes,
}) {
  const shared = {
    student: String(student || '').trim(),
    crm_contact: String(contact || '').trim() || null,
    idempotency_key: idempotencyKey,
    correlation_id: correlationId || idempotencyKey,
    supersedes: supersedes || null,
  }

  if (kind === 'event') {
    return {
      ...shared,
      crm_event: record,
      status: status || 'Registered',
      registered_at: occurredAt || null,
      feedback_notes: String(notes || '').trim() || null,
    }
  }

  return {
    ...shared,
    crm_campaign: record,
    touched_at: occurredAt || null,
    source: source || 'Manual',
    notes: String(notes || '').trim() || null,
  }
}

export function attributionTimeline(dto = {}) {
  const entries = dto.timeline?.items || dto.timeline || dto.evidence || dto.items || []
  return [...entries]
    .map((entry) => ({
      name: entry.name || entry.evidence_name || '',
      student: entry.student || entry.student_id || entry.student_ref || '',
      occurredAt:
        entry.occurred_at ||
        entry.touched_at ||
        entry.registered_at ||
        entry.creation ||
        null,
      label:
        entry.label || entry.source || entry.status || entry.evidence_type || __('Attribution evidence'),
      source: entry.source || '',
      status: entry.status || '',
      notes: entry.notes || entry.feedback_notes || '',
      superseded: Boolean(entry.superseded || entry.is_superseded),
    }))
    .sort(
      (left, right) =>
        String(right.occurredAt || '').localeCompare(String(left.occurredAt || '')) ||
        String(right.name).localeCompare(String(left.name)),
    )
}

export function attributionMetrics(dto = {}) {
  const metrics = dto.metrics || dto.funnel || dto.aggregate || dto.summary || {}
  const allowlist = [
    ['students', __('Students')],
    ['lead', __('Lead')],
    ['mql', __('MQL')],
    ['applicant', __('Applicant')],
    ['enrolled', __('Enrolled')],
    ['lost', __('Lost')],
  ]
  return allowlist
    .filter(([key]) => metrics[key] !== undefined && metrics[key] !== null)
    .map(([key, label]) => ({ label, value: metrics[key] }))
}

export function safeAttributionError(error, fallback) {
  const status = error?.httpStatusCode || error?.status
  if ([401, 403].includes(status)) return __('You are not permitted to manage attribution.')
  if ([409, 412].includes(status)) return __('This attribution evidence changed. Reload and try again.')
  if (status === 422) return __('Please correct the attribution details and try again.')
  return error?.messages?.[0] || error?.message || fallback
}
