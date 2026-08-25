import { describe, expect, it } from 'vitest'
import {
  buildIntakePayload,
  buildOwnershipPayload,
  intakeResultKind,
  isValidIntakeReviewDecision,
  isStaleOwnershipError,
  reviewCandidateOptions,
} from '../../src/utils/studentOwnership'

describe('student ownership command UI helpers', () => {
  it('keeps strong and weak identifiers explicit in an intake payload', () => {
    expect(
      buildIntakePayload(
        {
          student_name: '  Lan  ',
          admission_year: '2026',
          branch: 'HN',
          phone: '0901',
          email: '',
        },
        { id_number: ' 0123 ', source_record_id: 'manual-1' },
      ),
    ).toEqual({
      payload: {
        student_name: 'Lan',
        admission_year: '2026',
        branch: 'HN',
        owning_team: undefined,
        phone: '0901',
        email: undefined,
        id_number: '0123',
      },
      source_namespace: 'crm.manual_intake',
      source_record_id: 'manual-1',
    })
  })

  it('keeps the full manual student form fields in the intake payload', () => {
    expect(
      buildIntakePayload(
        {
          student_name: 'Lan',
          admission_year: '2026',
          branch: 'CAMPUS-1',
          enrollment_status: 'Mới',
          source: 'Website',
          province: 'HN',
          high_school: 'HS-1',
          ward: 'W-1',
          major: 'Major-1',
          aspiration: 'Aspiration-1',
          phone: '0900000000',
          id_number: '012345678901',
          owning_team: 'POOL-1',
        },
        { source_record_id: 'manual-full-1' },
      ).payload,
    ).toMatchObject({
      enrollment_status: 'Mới',
      source: 'Website',
      branch: 'CAMPUS-1',
      province: 'HN',
      high_school: 'HS-1',
      ward: 'W-1',
      major: 'Major-1',
      aspiration: 'Aspiration-1',
      id_number: '012345678901',
      owning_team: 'POOL-1',
    })
  })

  it('maps exactly one ownership target into the command contract', () => {
    expect(
      buildOwnershipPayload({
        student: 'STU-1',
        target: { kind: 'pool', id: 'TEAM-1' },
        reason: ' Capacity ',
        revision: 4,
        correlationId: 'c',
        idempotencyKey: 'i',
      }),
    ).toMatchObject({
      student: 'STU-1',
      target_kind: 'pool',
      target_id: null,
      target_team_id: 'TEAM-1',
      reason: 'Capacity',
      expected_revision: 4,
    })
  })

  it('recognizes only terminal intake results and stale conflicts', () => {
    expect(intakeResultKind({ status: 'created' })).toBe('created')
    expect(intakeResultKind({ outcome: 'review_required' })).toBe(
      'review_required',
    )
    expect(intakeResultKind({ status: 'unknown' })).toBeNull()
    expect(
      isStaleOwnershipError({ messages: ['STALE_OWNERSHIP_REVISION'] }),
    ).toBe(true)
  })

  it('normalizes accessible review candidates without exposing duplicate choices', () => {
    expect(
      reviewCandidateOptions({
        proposed_identity: 'IDENTITY-1',
        candidates: [
          { identity_id: 'IDENTITY-1', masked_label: 'Identity ending 1234' },
          { identity_id: 'IDENTITY-2', masked_label: 'Identity ending 5678' },
        ],
      }),
    ).toEqual([
      { label: 'Identity ending 1234', value: 'IDENTITY-1' },
      { label: 'Identity ending 5678', value: 'IDENTITY-2' },
    ])
  })

  it('requires evidence and the decision-specific verified input', () => {
    expect(
      isValidIntakeReviewDecision({
        decision: 'reject',
        evidence: 'Verified duplicate',
      }),
    ).toBe(true)
    expect(
      isValidIntakeReviewDecision({
        decision: 'attach_identity',
        evidence: 'Verified duplicate',
      }),
    ).toBe(false)
    expect(
      isValidIntakeReviewDecision({
        decision: 'attach_identity',
        identityId: 'IDENTITY-1',
        availableIdentityIds: ['IDENTITY-1'],
        evidence: 'Verified duplicate',
      }),
    ).toBe(true)
    expect(
      isValidIntakeReviewDecision({
        decision: 'attach_identity',
        identityId: 'IDENTITY-2',
        availableIdentityIds: ['IDENTITY-1'],
        evidence: 'Verified duplicate',
      }),
    ).toBe(false)
    expect(
      isValidIntakeReviewDecision({
        decision: 'approve_new_identity',
        evidence: 'Verified document',
        identityData: { student_name: 'Lan' },
      }),
    ).toBe(false)
    expect(
      isValidIntakeReviewDecision({
        decision: 'approve_new_identity',
        evidence: 'Verified document',
        identityData: { student_name: 'Lan', national_id: '012345678901' },
      }),
    ).toBe(true)
    expect(
      isValidIntakeReviewDecision({
        decision: 'approve_new_identity',
        evidence: 'Verified document',
        identityData: { student_name: 'Lan', national_id: 'not-an-id' },
      }),
    ).toBe(false)
  })
})
