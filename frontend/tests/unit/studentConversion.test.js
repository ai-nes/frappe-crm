import { describe, expect, it } from 'vitest'
import {
  buildStudentConversionPayload,
  contactConversionHistory,
  conversionErrorState,
  studentConversionState,
} from '../../src/utils/studentConversion'

describe('Student conversion UI helpers', () => {
  it('builds the exact server-owned conversion command payload', () => {
    expect(buildStudentConversionPayload({
      student: ' STU-1 ', lifecycleRevision: '7', idempotencyKey: 'idem-1', correlationId: 'corr-1',
    })).toEqual({
      student: 'STU-1', expected_lifecycle_revision: 7,
      idempotency_key: 'idem-1', correlation_id: 'corr-1',
    })
  })

  it('only enables conversion when the server advertises the capability', () => {
    expect(studentConversionState({ lifecycle: { revision: 5, current_stage: 'Enrolled' } })).toMatchObject({
      advertised: false, converted: false, revision: 5,
    })
    expect(studentConversionState({
      lifecycle: { revision: 5, current_stage: 'Applicant' },
      conversion: { can_convert: true },
    })).toMatchObject({ advertised: true, converted: false, revision: 5 })
  })

  it('keeps retries on the same idempotency payload', () => {
    const first = buildStudentConversionPayload({ student: 'STU-1', lifecycleRevision: 3, idempotencyKey: 'stable-key' })
    const retry = buildStudentConversionPayload({ student: 'STU-1', lifecycleRevision: 3, idempotencyKey: 'stable-key' })
    expect(retry).toEqual(first)
    expect(retry.correlation_id).toBe('stable-key')
  })

  it('redacts inaccessible Contact case history without retaining Student PII', () => {
    expect(contactConversionHistory({
      history: { items: [
        { name: 'CONV-1', student: 'STU-1', student_name: 'Visible Student', converted_at: '2026-08-25T10:00:00Z' },
        { name: 'CONV-2', student: 'STU-secret', student_name: 'Secret Student', redacted: true },
      ], next_cursor: 'next' },
      redacted_count: 1,
    })).toEqual({
      items: [
        { name: 'CONV-1', redacted: false, student: 'STU-1', label: 'Visible Student', convertedAt: '2026-08-25T10:00:00Z' },
        { name: 'CONV-2', redacted: true, student: '', label: 'Restricted Student case', convertedAt: null },
      ],
      nextCursor: 'next', redactedCount: 1,
    })
  })

  it('maps server conditions to explicit recovery states', () => {
    expect(conversionErrorState({ error_code: 'STALE_REVISION' })).toMatchObject({ kind: 'stale', reload: true, retryable: false })
    expect(conversionErrorState({ status: 403 })).toMatchObject({ kind: 'denied', retryable: false })
    expect(conversionErrorState({ message: 'Network interrupted' })).toMatchObject({ kind: 'retry', retryable: true })
  })
})
