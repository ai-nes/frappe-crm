import { describe, expect, it } from 'vitest'
import {
  isActionOverdue,
  recommendationItem,
  actionItem,
  transitionOptions,
  validateRecommendationDecision,
} from '../../src/utils/studentDecision'

describe('student decision UI helpers', () => {
  it('keeps Student ID separate from its display name', () => {
    expect(recommendationItem({ recommendation: 'REC-1', student: 'STU-1', student_name: 'Mai Nguyen' })).toMatchObject({
      recommendation: 'REC-1', student: 'STU-1', studentName: 'Mai Nguyen',
    })
  })

  it('maps the director recommendation read model and surfaces the AI payload verbatim', () => {
    const item = recommendationItem({
      id: 'REC-9',
      rank: 2,
      recommendationKey: 'call-confirm-intent',
      studentId: 'ENR-2026-00003',
      studentName: 'Mai Nguyen',
      actionId: 'ACT-CALL',
      aiPayload: { actionType: 'CALL', channel: 'phone', timing: '2026-09-05T09:00:00.000Z', objective: 'Confirm intent' },
      evaluation: { id: 'EVAL-1', disposition: 'ACT', status: 'settled' },
      generatedAt: '2026-09-04T02:00:00+07:00',
    })
    expect(item.id).toBe('REC-9')
    expect(item.recommendation).toBe('REC-9')
    expect(item.rank).toBe(2)
    expect(item.student).toBe('ENR-2026-00003')
    expect(item.action).toBe('CALL')
    expect(item.reason).toBe('Confirm intent')
    expect(item.aiPayload).toEqual({ actionType: 'CALL', channel: 'phone', timing: '2026-09-05T09:00:00.000Z', objective: 'Confirm intent' })
    expect(item.evaluation).toEqual({ id: 'EVAL-1', disposition: 'ACT', status: 'settled' })
    expect(item.permittedDecisions).toContain('dismissed')
  })

  it('adapts planned v2 action DTOs and only exposes server-advertised transitions', () => {
    const action = actionItem({ name: 'ACT-1', student: 'STU-1', student_name: 'Mai Nguyen', execution_status: 'planned', due_at: '2026-08-20T08:00:00Z', permitted_transitions: [{ status: 'in_progress', label: 'Start' }] })
    expect(action.overdue).toBe(true)
    expect(transitionOptions(action)).toEqual([{ value: 'in_progress', label: 'Start' }])
  })

  it('requires the decision evidence that changes the command shape', () => {
    expect(validateRecommendationDecision({ status: 'accepted' })).toBeTruthy()
    expect(validateRecommendationDecision({ status: 'deferred', deferKind: 'archive', reason: '' })).toBeTruthy()
    expect(validateRecommendationDecision({ status: 'deferred', deferKind: 'revisit', revisitAt: '2026-08-30T10:00' })).toBe('')
  })

  it('does not mark terminal actions overdue', () => {
    expect(isActionOverdue({ status: 'completed', dueAt: '2026-08-20T08:00:00Z' })).toBe(false)
  })
})
