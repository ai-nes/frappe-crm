import { describe, expect, it } from 'vitest'
import {
  buildLifecycleTransitionPayload,
  isLifecycleCommandAllowed,
  isOverdueNextAction,
  lifecycleTargets,
  safeLifecycleError,
} from '../../src/utils/studentEngagement'

describe('student engagement UI helpers', () => {
  it('builds an auditable lifecycle command without mutating Student fields', () => {
    expect(
      buildLifecycleTransitionPayload({
        student: 'STU-1',
        target: 'Applicant',
        reason: ' Verified documents ',
        evidence: ' OUTCOME-1, TASK-1 ',
        revision: 7,
        idempotencyKey: 'idem-1',
        correlationId: 'corr-1',
      }),
    ).toEqual({
      student: 'STU-1',
      target_stage: 'Applicant',
      reason: 'Verified documents',
      evidence_refs: ['OUTCOME-1', 'TASK-1'],
      expected_revision: 7,
      idempotency_key: 'idem-1',
      correlation_id: 'corr-1',
    })
  })

  it('accepts multiple evidence references separated by new lines', () => {
    expect(
      buildLifecycleTransitionPayload({
        student: 'STU-1',
        target: 'Enrolled',
        reason: '',
        evidence: 'intent:CRM Intent:INT-1\ndocument:CRM Student Document:DOC-1',
        revision: 7,
        idempotencyKey: 'idem-1',
        correlationId: 'corr-1',
      }).evidence_refs,
    ).toEqual(['intent:CRM Intent:INT-1', 'document:CRM Student Document:DOC-1'])
  })

  it('uses only server-provided permitted targets', () => {
    const lifecycle = {
      allowed_targets: [
        { stage: 'MQL', label: 'Marketing qualified lead', requires_evidence: true },
        { stage: 'Lost', label: 'Lost', requires_reason: true },
      ],
    }
    expect(lifecycleTargets(lifecycle)).toEqual([
      { label: 'Marketing qualified lead', value: 'MQL', requiresEvidence: true, requiresReason: false },
      { label: 'Lost', value: 'Lost', requiresEvidence: false, requiresReason: true },
    ])
    expect(isLifecycleCommandAllowed({ target: 'MQL', reason: '', evidence: 'OUTCOME-1', lifecycle })).toBe(true)
    expect(isLifecycleCommandAllowed({ target: 'Lost', reason: 'No longer interested', evidence: '', lifecycle })).toBe(true)
    expect(isLifecycleCommandAllowed({ target: 'Applicant', reason: 'Verified', evidence: 'OUTCOME-1', lifecycle })).toBe(false)
  })

  it('presents only incomplete past-due actions as overdue', () => {
    const now = new Date('2026-08-25T10:00:00Z')
    expect(isOverdueNextAction({ due_at: '2026-08-25T09:59:00Z', status: 'Open' }, now)).toBe(true)
    expect(isOverdueNextAction({ due_at: '2026-08-25T09:59:00Z', status: 'Completed' }, now)).toBe(false)
    expect(isOverdueNextAction({ due_at: 'not-a-date', status: 'Open' }, now)).toBe(false)
  })

  it('keeps conflict and permission errors explicit', () => {
    expect(safeLifecycleError({ status: 403 }, 'Fallback')).toBe('You are not permitted to change this lifecycle.')
    expect(safeLifecycleError({ httpStatusCode: 409 }, 'Fallback')).toBe('This lifecycle changed. Reload the Student and review the current state.')
    expect(safeLifecycleError({ messages: ['Missing evidence'] }, 'Fallback')).toBe('Missing evidence')
  })
})
