import { describe, expect, it } from 'vitest'
import { getStudentFunnelFilters } from '../../src/utils/studentFunnel'

describe('student funnel filters', () => {
  it('shows every enrolled Student from the authoritative lifecycle stage', () => {
    expect(getStudentFunnelFilters('enrolled')).toEqual({
      lifecycle_stage: 'Enrolled',
    })
  })

  it('keeps enrolled and lost Students out of the prospective funnel', () => {
    expect(getStudentFunnelFilters('intake')).toEqual({
      lifecycle_stage: ['not in', ['Enrolled', 'Lost']],
    })
  })
})
