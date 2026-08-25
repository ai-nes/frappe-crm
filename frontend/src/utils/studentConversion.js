export const studentConversionApi = Object.freeze({
  convert: 'crm.api.student_conversion.convert_student',
  getContactHistory: 'crm.api.contact_conversion.get_contact_conversion_history',
})

export function createStudentConversionCommandId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function buildStudentConversionPayload({ student, lifecycleRevision, idempotencyKey, correlationId }) {
  return {
    student: String(student || '').trim(),
    expected_lifecycle_revision: Number(lifecycleRevision),
    idempotency_key: idempotencyKey,
    correlation_id: correlationId || idempotencyKey,
  }
}

// The context contract is deliberately tolerant during the staged Phase 8
// rollout, but conversion is never enabled without an explicit server signal.
export function studentConversionState(context = {}) {
  const conversion = context.conversion || context.conversion_context || {}
  const lifecycle = context.lifecycle || {}
  const status = conversion.status || conversion.state || ''
  const contact = conversion.contact || conversion.contact_name || null
  const advertised = Boolean(
    conversion.can_convert ?? conversion.eligible ?? conversion.capabilities?.convert ?? context.capabilities?.convert,
  )

  return {
    advertised,
    converted: Boolean(contact || conversion.converted || ['converted', 'complete', 'completed'].includes(String(status).toLowerCase())),
    contact,
    revision: conversion.lifecycle_revision ?? conversion.expected_lifecycle_revision ?? lifecycle.revision ?? lifecycle.lifecycle_revision ?? null,
    status,
    convertedAt: conversion.converted_at || conversion.timestamp || null,
    actor: conversion.actor_label || conversion.actor || null,
  }
}

export function conversionResult(dto = {}) {
  return {
    status: dto.status || 'completed',
    student: dto.student || dto.student_name || '',
    contact: dto.contact || dto.contact_name || dto.result?.contact || '',
    conversion: dto.conversion || dto.conversion_name || dto.result?.conversion || '',
    receipt: dto.receipt || dto.receipt_name || dto.result?.receipt || '',
    replayed: Boolean(dto.replayed || dto.is_replay),
    lifecycleRevision: dto.lifecycle_revision ?? dto.revision ?? null,
  }
}

export function contactConversionHistory(dto = {}) {
  const source = dto.history?.items || dto.history || dto.items || dto.conversions || []
  const items = Array.isArray(source) ? source : []
  return {
    items: items.map((entry) => {
      const redacted = Boolean(entry.redacted || entry.is_redacted || entry.visible === false || entry.can_read === false)
      return {
        name: entry.name || entry.conversion || entry.conversion_name || '',
        redacted,
        // Only expose the approved identifier/label when the server explicitly
        // marked this case visible. Never fall back to a potentially leaked name.
        student: redacted ? '' : (entry.student || entry.student_id || ''),
        label: redacted
          ? __('Restricted Student case')
          : (entry.student_label || entry.student_name || entry.student || __('Student case')),
        convertedAt: entry.converted_at || entry.creation || entry.timestamp || null,
      }
    }),
    nextCursor: dto.history?.next_cursor || dto.next_cursor || dto.cursor || null,
    redactedCount: Number(dto.redacted_count || dto.history?.redacted_count || 0),
  }
}

export function conversionErrorState(error) {
  const code = String(error?.code || error?.error_code || error?.exc_type || error?.messages?.[0] || '').toUpperCase()
  const status = Number(error?.httpStatusCode || error?.status || 0)
  if ([401, 403].includes(status) || code.includes('PERMISSION') || code.includes('NOT_PERMITTED')) {
    return { kind: 'denied', retryable: false, reload: false, message: __('You are not permitted to convert this Student.') }
  }
  if (code.includes('STALE_REVISION') || status === 412) {
    return { kind: 'stale', retryable: false, reload: true, message: __('This Student changed. Reload and review the current conversion state.') }
  }
  if (code.includes('CONVERSION_CONDITION_FAILED') || code.includes('NOT_ENROLLED')) {
    return { kind: 'condition', retryable: false, reload: true, message: __('Only an enrolled Student can be converted.') }
  }
  if (code.includes('IDEMPOTENCY_KEY_REUSED')) {
    return { kind: 'conflict', retryable: false, reload: true, message: __('This conversion request conflicts with an earlier request. Reload the Student.') }
  }
  if (code.includes('PENDING') || status === 409) {
    return { kind: 'pending', retryable: false, reload: true, message: __('The conversion result is being resolved. Reload the Student.') }
  }
  if (status === 422) return { kind: 'invalid', retryable: false, reload: true, message: __('The Student no longer meets the conversion requirements.') }
  return {
    kind: 'retry', retryable: true, reload: false,
    message: error?.messages?.[0] || error?.message || __('Unable to convert this Student. You can retry safely.'),
  }
}

export function safeConversionError(error, fallback) {
  return conversionErrorState(error).message || fallback
}
