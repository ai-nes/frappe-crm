import { describe, expect, it } from 'vitest'
import {
  admissionsActionDefinitions,
  buildAdmissionsActionPayload,
  fieldsForAdmissionsAction,
  admissionsSummaryTranslation,
  validateAdmissionsAction,
} from '../../src/utils/studentAdmissionsActions'

describe('student admissions actions', () => {
  it('exposes the operational actions required by the Student Detail workflow', () => {
    expect(admissionsActionDefinitions.map((item) => item.value)).toEqual(expect.arrayContaining([
      'digital_signal',
      'call_attempt',
      'call_success',
      'brochure_sent',
      'major_update',
      'lifecycle_transition',
      'event_invite',
      'event_checkin',
      'scholarship_interest',
      'create_task',
      'create_insight_note',
      'assign_counselor',
    ]))
  })

  it('validates only fields relevant to the selected action', () => {
    expect(validateAdmissionsAction('digital_signal', {})).toContain('signal')
    expect(validateAdmissionsAction('digital_signal', { signal: 'Zalo chat' })).toBe('')
    expect(fieldsForAdmissionsAction('assign_counselor').map((field) => field.name)).toEqual(['counselor', 'team', 'reason'])
  })

  it('builds a stable server command envelope without exposing UI-only fields', () => {
    expect(buildAdmissionsActionPayload({
      student: 'ENR-0001',
      action: 'call_success',
      expectedRevision: 4,
      payload: { summary: 'Connected' },
      idempotencyKey: 'call_success:1',
      occurredAt: '2026-08-26T10:00:00.000Z',
    })).toEqual({
      student: 'ENR-0001',
      action: 'call_success',
      occurred_at: '2026-08-26T10:00:00.000Z',
      expected_revision: 4,
      idempotency_key: 'call_success:1',
      correlation_id: 'call_success:1',
      payload: { summary: 'Connected' },
    })
  })

  it('translates controlled summaries but preserves free-form activity text', () => {
    expect(admissionsSummaryTranslation('Call attempt')).toEqual({ key: 'Call attempt', args: [] })
    expect(admissionsSummaryTranslation('Invited to FPTU Open Day')).toEqual({
      key: 'Invited to {0}',
      args: ['FPTU Open Day'],
    })
    expect(admissionsSummaryTranslation('Family prefers another campus')).toBeNull()
  })
})
