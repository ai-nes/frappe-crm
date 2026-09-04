import { describe, expect, it } from 'vitest'
import {
  admissionsActionDefinitions,
  buildAdmissionsActionPayload,
  fieldsForAdmissionsAction,
  admissionsSummaryTranslation,
  validateAdmissionsAction,
  buildRecommendationDecisionCommand,
  diffRecommendationDelta,
  resolveRecommendationOperation,
  RECOMMENDATION_OPERATIONS,
  TASK_CREATING_OPERATIONS,
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

describe('recommendation HITL command', () => {
  const aiPayload = Object.freeze({
    actionId: 'ACT-1',
    action: 'CALL',
    actionType: 'CALL',
    channel: 'phone',
    timing: '2026-09-05T09:00:00.000Z',
    objective: 'Confirm application intent',
  })
  const base = { recommendation: 'REC-1', expectedRevision: 3, idempotencyKey: 'rec-1:accept' }

  it('accept produces exactly one command with an empty delta and no payload echo', () => {
    const command = buildRecommendationDecisionCommand({ ...base, operation: 'ACCEPT', aiPayload })
    expect(command).toEqual({
      name: 'REC-1',
      recommendation: 'REC-1',
      expected_revision: 3,
      operation: 'ACCEPT',
      delta: {},
      idempotency_key: 'rec-1:accept',
    })
    expect(command).not.toHaveProperty('aiPayload')
  })

  it('changed timing/channel leaves the AI proposal untouched and the Task uses human values', () => {
    const draft = { channel: 'zalo', timing: '2026-09-06T02:00:00.000Z' }
    const command = buildRecommendationDecisionCommand({ ...base, operation: 'ACCEPT_WITH_CHANGES', aiPayload, draft })
    expect(command.operation).toBe('ACCEPT_WITH_CHANGES')
    expect(command.delta).toEqual({ channel: 'zalo', timing: '2026-09-06T02:00:00.000Z' })
    // AI payload object is never mutated by the builder.
    expect(aiPayload.channel).toBe('phone')
    expect(aiPayload.timing).toBe('2026-09-05T09:00:00.000Z')
    expect(diffRecommendationDelta(aiPayload, { channel: 'phone', timing: aiPayload.timing })).toEqual({})
  })

  it('rejects an Action identity change on the client before any command is built', () => {
    expect(() =>
      buildRecommendationDecisionCommand({
        ...base,
        operation: 'ACCEPT_WITH_CHANGES',
        aiPayload,
        draft: { actionId: 'ACT-2', channel: 'zalo' },
      }),
    ).toThrow(/Action identity/)
  })

  it('reject / defer / dismiss carry no Task semantics and an empty delta', () => {
    for (const operation of ['REJECT', 'DEFER', 'DISMISS']) {
      const command = buildRecommendationDecisionCommand({ ...base, operation, aiPayload, idempotencyKey: `k:${operation}` })
      expect(command.operation).toBe(operation)
      expect(command.delta).toEqual({})
      expect(TASK_CREATING_OPERATIONS).not.toContain(operation)
    }
  })

  it('resolves an accept intent to ACCEPT_WITH_CHANGES only when an allowlisted param changed', () => {
    expect(resolveRecommendationOperation('ACCEPT', aiPayload, {})).toBe('ACCEPT')
    expect(resolveRecommendationOperation('ACCEPT', aiPayload, { channel: 'phone' })).toBe('ACCEPT')
    expect(resolveRecommendationOperation('ACCEPT', aiPayload, { channel: 'email' })).toBe('ACCEPT_WITH_CHANGES')
    expect(RECOMMENDATION_OPERATIONS).toContain('DISMISS')
  })
})
