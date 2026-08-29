import { describe, expect, it } from 'vitest'
import { formatWorkspaceTimestamp, workspaceDefinition, workspaceKpis, workspaceRows } from '@/data/leadSalesWorkspaceAdapters'

describe('Lead Sales workspace DTO adapters', () => {
  it('adapts the server KPI object without calculating any totals', () => {
    expect(workspaceKpis({ kpis: { active_students: 3, unassigned_students: 2, breached_sla: 1 } })).toEqual([
      { key: 'active_students', label: 'Hồ sơ đang xử lý', value: 3 },
      { key: 'unassigned_students', label: 'Hồ sơ chưa phân công', value: 2 },
      { key: 'breached_sla', label: 'SLA đã trễ', value: 1 },
    ])
  })

  it('keeps missing collection DTOs empty and exposes server metadata', () => {
    expect(workspaceRows({}, 'members')).toEqual([])
    expect(workspaceDefinition({ definition: { scope: 'current_student_permission_scope' } })).toBe('Phạm vi hồ sơ hiện tại của nhóm')
    expect(formatWorkspaceTimestamp({ generated_at: '2026-08-28 10:00:00' })).toBe('2026-08-28 10:00:00')
  })
})
