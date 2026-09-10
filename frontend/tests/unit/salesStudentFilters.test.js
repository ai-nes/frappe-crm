import { describe, expect, it } from 'vitest'
import { getSalesStudentFilters } from '../../src/utils/salesStudentFilters'

describe('getSalesStudentFilters', () => {
  it('maps sales sidebar views to student filters', () => {
    expect(getSalesStudentFilters('new')).toEqual({ enrollment_status: 'Mới' })
    expect(getSalesStudentFilters('won')).toEqual({ lifecycle_stage: 'Enrolled' })
    expect(getSalesStudentFilters('unassigned')).toEqual({
      owner_staff: ['is', 'not set'],
    })
  })

  it('returns no extra filters for an unknown view', () => {
    expect(getSalesStudentFilters('unknown')).toEqual({})
  })
})
