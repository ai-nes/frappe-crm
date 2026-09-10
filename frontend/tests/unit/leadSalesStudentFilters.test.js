import { describe, expect, it } from 'vitest'
import {
  getLeadSalesStudentContext,
  getLeadSalesStudentFilters,
} from '../../src/utils/leadSalesStudentFilters'

describe('getLeadSalesStudentFilters', () => {
  it('maps only the allowlisted unassigned Lead Sales view to a Student filter', () => {
    expect(getLeadSalesStudentFilters({ lead_view: 'unassigned' })).toEqual({
      owner_staff: ['is', 'not set'],
    })
  })

  it('makes the stage and advisor views exhaustive instead of applying the intake funnel', () => {
    expect(getLeadSalesStudentContext({ lead_view: 'by_stage' })).toMatchObject({
      bypassFunnel: true,
      filters: {},
    })
    expect(getLeadSalesStudentContext({ lead_view: 'by_agent' })).toMatchObject({
      bypassFunnel: true,
      defaultGroupByField: 'owner_staff',
      filters: {},
    })
  })

  it('does not treat Lost as the cold/abandoned queue', () => {
    expect(getLeadSalesStudentContext({ lead_view: 'cold_abandoned' })).toMatchObject({
      temporary: true,
      filters: {},
    })
    expect(getLeadSalesStudentFilters({ lead_view: 'cold_abandoned' })).toEqual({})
  })

  it('ignores unrelated and legacy query parameters', () => {
    expect(getLeadSalesStudentContext({ view: 'My Students' })).toEqual({})
    expect(getLeadSalesStudentContext({ owner: 'unassigned' })).toEqual({})
    expect(getLeadSalesStudentContext({ stage: 'cold' })).toEqual({})
  })
})
