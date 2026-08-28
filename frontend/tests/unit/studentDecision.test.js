import { describe, expect, it } from 'vitest'
import {
  buildRecommendationDecisionPayload,
  isActionOverdue,
  recommendationItem,
  salesActionItem,
  transitionOptions,
  validateRecommendationDecision,
} from '../../src/utils/studentDecision'

describe('student decision UI helpers', () => {
  it('keeps Student ID separate from its display name', () => {
    expect(recommendationItem({ recommendation: 'REC-1', student: 'STU-1', student_name: 'Mai Nguyen' })).toMatchObject({
      recommendation: 'REC-1', student: 'STU-1', studentName: 'Mai Nguyen',
    })
  })

  it('adapts planned v2 action DTOs and only exposes server-advertised transitions', () => {
    const action = salesActionItem({ name: 'ACT-1', student: 'STU-1', student_name: 'Mai Nguyen', execution_status: 'planned', due_at: '2026-08-20T08:00:00Z', permitted_transitions: [{ status: 'in_progress', label: 'Start' }] })
    expect(action.overdue).toBe(true)
    expect(transitionOptions(action)).toEqual([{ value: 'in_progress', label: 'Start' }])
  })

  it('requires the decision evidence that changes the command shape', () => {
    expect(validateRecommendationDecision({ status: 'accepted' })).toBeTruthy()
    expect(validateRecommendationDecision({ status: 'deferred', deferKind: 'archive', reason: '' })).toBeTruthy()
    expect(validateRecommendationDecision({ status: 'deferred', deferKind: 'revisit', revisitAt: '2026-08-30T10:00' })).toBe('')
  })

  it('builds an idempotent accept command without client authority', () => {
    expect(buildRecommendationDecisionPayload({ item: { recommendation: 'REC-1', revision: '7' }, status: 'accepted', dueAt: '2026-08-30T10:00:00.000Z', assignee: 'STAFF-1', idempotencyKey: 'idem-1', correlationId: 'corr-1' })).toEqual({
      name: 'REC-1', expected_revision: '7', status: 'accepted', decision_reason: null, due_at: '2026-08-30T10:00:00.000Z', assignee_staff: 'STAFF-1', idempotency_key: 'idem-1', correlation_id: 'corr-1',
    })
  })

  it('does not mark terminal actions overdue', () => {
    expect(isActionOverdue({ status: 'completed', dueAt: '2026-08-20T08:00:00Z' })).toBe(false)
  })
})
