import { describe, expect, it, vi } from 'vitest'

vi.mock('frappe-ui', () => ({ createResource: () => ({}) }))

import {
  assignmentWorkspaceFilterQuery,
  assignmentWorkspacePolicyLabel,
  assignmentWorkspaceStatusLabel,
  normalizeAssignmentWorkspaceRows,
  serializeAssignmentWorkspaceFilters,
} from '../../src/data/assignmentWorkspace'

describe('assignment workspace data contract', () => {
  it('serializes only active URL filters', () => {
    expect(assignmentWorkspaceFilterQuery({ campus: 'HCM', status: 'all', search: '' })).toEqual({
      campus: 'HCM',
    })
    expect(JSON.parse(serializeAssignmentWorkspaceFilters({ campus: 'HCM', status: 'unassigned' }))).toEqual({
      campus: 'HCM',
      status: 'unassigned',
    })
    expect(serializeAssignmentWorkspaceFilters({})).toBeUndefined()
  })

  it('builds expandable relationships from server parent IDs', () => {
    const rows = normalizeAssignmentWorkspaceRows([
      { id: 'campus:1', level: 'campus', has_children: false },
      { id: 'zone:1', level: 'zone', parent_id: 'campus:1' },
      { id: 'staff:1', level: 'staff', parent_id: 'zone:1' },
    ])

    expect(rows[0]).toMatchObject({ has_children: true, children: ['zone:1'] })
    expect(rows[1]).toMatchObject({ has_children: true, children: ['staff:1'] })
    expect(rows[2]).toMatchObject({ has_children: false, children: [] })
  })

  it('keeps status terminology centralized for the UI', () => {
    expect(assignmentWorkspaceStatusLabel('unassigned')).toBe('Chưa cấu hình')
    expect(assignmentWorkspaceStatusLabel('unknown')).toBe('unknown')
  })

  it('keeps routing strategy terminology understandable for operators', () => {
    expect(assignmentWorkspacePolicyLabel('round_robin')).toBe('Luân phiên công bằng')
    expect(assignmentWorkspacePolicyLabel('weighted_score')).toBe('Chấm điểm có trọng số')
  })
})
