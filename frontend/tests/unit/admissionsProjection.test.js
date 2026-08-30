import { describe, expect, it } from 'vitest'
import {
  buildProjectionFilters,
  projectionEndpoint,
  projectionToDashboardItems,
} from '@/utils/admissionsProjection'

describe('admissions projection contract', () => {
  it('maps UI filters to the server-owned filter vocabulary', () => {
    expect(buildProjectionFilters({
      fromDate: '2026-01-01',
      toDate: '2026-01-31',
      advancedFilters: { admissionTerm: '2026', program: 'CS', campus: 'HN' },
      team: 'all',
    })).toMatchObject({ from: '2026-01-01', to: '2026-01-31', admission_year: '2026', major: 'CS', campus: 'HN' })
  })

  it('uses projection endpoints and never derives KPI values from mock rows', () => {
    expect(projectionEndpoint('sales')).toContain('admissions_projections')
    expect(projectionToDashboardItems({ data: { application_count: 4, enrolled_count: 1 } })).toHaveLength(2)
  })
})
