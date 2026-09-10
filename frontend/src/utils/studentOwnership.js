const terminalIntakeStatuses = new Set([
  'attached',
  'created',
  'review_required',
])
const intakeReviewDecisions = new Set([
  'attach_identity',
  'approve_new_identity',
  'reject',
])

export function createCommandId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID)
    return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function intakeResultKind(result) {
  const outcome = result?.outcome || result?.status
  return terminalIntakeStatuses.has(outcome) ? outcome : null
}

export function intakeAssignmentExpectation(profile) {
  if (profile === 'sales') {
    return {
      kind: 'self',
      message: 'This student will be assigned to you automatically.',
    }
  }
  if (profile === 'lead_sales') {
    return {
      kind: 'team',
      message: 'This student will be placed in your team pool automatically.',
    }
  }
  return {
    kind: 'automatic',
    message: 'Assignment will be determined automatically from your access.',
  }
}

export function isServerManagedIntakeProfile(profile) {
  return profile === 'sales' || profile === 'lead_sales'
}

export function reviewCandidateOptions(review) {
  const candidates = Array.isArray(review?.candidates) ? review.candidates : []
  const proposedIdentity =
    review?.proposed_identity || review?.candidate_identity
  const byId = new Map()

  for (const candidate of candidates) {
    const value = candidate?.identity_id || candidate?.name
    if (!value) continue
    const maskedLabel = candidate?.masked_label
    byId.set(value, {
      label:
        maskedLabel && maskedLabel !== value
          ? maskedLabel
          : __('Verified identity'),
      value,
    })
  }
  if (proposedIdentity && !byId.has(proposedIdentity)) {
    byId.set(proposedIdentity, {
      label: __('Verified identity'),
      value: proposedIdentity,
    })
  }
  return [...byId.values()]
}

export function isValidIntakeReviewDecision({
  decision,
  evidence,
  identityId,
  identityData,
  availableIdentityIds,
}) {
  if (!intakeReviewDecisions.has(decision) || !String(evidence || '').trim())
    return false
  if (decision === 'attach_identity') {
    if (!identityId) return false
    return !availableIdentityIds || availableIdentityIds.includes(identityId)
  }
  if (decision === 'approve_new_identity') {
    return Boolean(
      String(identityData?.student_name || '').trim() &&
      (String(identityData?.phone || '').trim() ||
        String(identityData?.email || '').trim()),
    )
  }
  return true
}

export function buildIntakePayload(form, identifiers) {
  const optionalFields = [
    'enrollment_status',
    'source',
    'province',
    'high_school',
    'ward',
    'major',
    'aspiration',
    'current_grade',
    'study_stage',
  ]
  const optionalPayload = Object.fromEntries(
    optionalFields
      .filter((fieldname) => form[fieldname])
      .map((fieldname) => [fieldname, form[fieldname]]),
  )
  return {
    payload: {
      student_name: form.student_name?.trim(),
      admission_year: form.admission_year,
      branch: form.branch,
      phone: form.phone?.trim() || undefined,
      email: form.email?.trim() || undefined,
      id_number:
        form.id_number?.trim() || identifiers.id_number?.trim() || undefined,
      ...optionalPayload,
    },
    source_namespace: 'crm.manual_intake',
    source_record_id: identifiers.source_record_id,
  }
}

export function buildOwnershipPayload({
  student,
  target,
  reason,
  revision,
  correlationId,
  idempotencyKey,
}) {
  return {
    student,
    target_kind: target.kind,
    target_id: target.kind === 'owner' ? target.id : null,
    target_team_id: target.kind === 'owner' ? target.teamId : target.id,
    reason: reason.trim(),
    idempotency_key: idempotencyKey,
    expected_revision: revision,
    correlation_id: correlationId,
  }
}

export function isStaleOwnershipError(error) {
  const text = [error?.exc_type, error?.message, ...(error?.messages || [])]
    .filter(Boolean)
    .join(' ')
  return text.includes('STALE_OWNERSHIP_REVISION')
}

export function safeCommandError(error, fallback) {
  const responseData = error?.response?.data || error?.data
  if (responseData) {
    const detail =
      responseData.message || responseData._server_messages || responseData.exc
    if (detail && detail !== 'Internal Server Error') {
      if (typeof detail === 'string' && detail.startsWith('[')) {
        try {
          const parsed = JSON.parse(detail)
          const text = parsed
            .map((item) => item.message || item)
            .filter(Boolean)
            .join('; ')
          if (text) return text.replace(/^[A-Z][A-Z0-9_]+:\s*/, '')
        } catch {
          // Continue with the raw detail.
        }
      }
      return String(detail).replace(/^[A-Z][A-Z0-9_]+:\s*/, '')
    }
  }
  const status = error?.httpStatusCode || error?.status
  if ([401, 403].includes(status))
    return __('You are not permitted to perform this action.')
  if (status === 409)
    return __('This record changed. Reload it and review the current state.')
  if (status === 422)
    return __('Please correct the highlighted information and try again.')
  const serverMessages = error?._server_messages || error?.server_messages
  if (serverMessages) {
    try {
      const parsed =
        typeof serverMessages === 'string'
          ? JSON.parse(serverMessages)
          : serverMessages
      const messages = Array.isArray(parsed) ? parsed : [parsed]
      const detail = messages
        .map((message) => {
          if (typeof message === 'string') {
            try {
              const decoded = JSON.parse(message)
              return decoded.message || decoded.exc || message
            } catch {
              return message
            }
          }
          return message?.message || message?.exc
        })
        .filter(Boolean)
        .join('; ')
      if (detail) return detail
    } catch {
      // Fall through to the other Frappe error fields.
    }
  }
  if (error?.messages?.length) return error.messages.join('; ')
  if (error?.exc && error.exc !== 'Internal Server Error') return error.exc
  return error?.message || fallback
}
