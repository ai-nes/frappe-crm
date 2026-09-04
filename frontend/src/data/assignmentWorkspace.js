import { createResource } from 'frappe-ui'

const API_PREFIX = 'crm.api.assignment_workspace.'

export const assignmentWorkspaceMethods = Object.freeze({
  overview: `${API_PREFIX}get_overview`,
  readiness: `${API_PREFIX}get_setup_readiness`,
  batchImpact: `${API_PREFIX}get_assignment_batch_impact`,
  batchCommand: `${API_PREFIX}apply_assignment_batch_command`,
  staffContext: `${API_PREFIX}get_staff_context`,
  staffContextCommand: `${API_PREFIX}apply_staff_context_command`,
})

export const assignmentWorkspaceLevels = Object.freeze([
  'campus',
  'province',
  'cluster',
  'zone',
  'high_school',
  'team',
  'staff',
])

export const assignmentWorkspaceStatusLabels = Object.freeze({
  healthy: 'Đã cấu hình',
  unassigned: 'Chưa cấu hình',
  needs_review: 'Cần rà soát',
  placeholder_zone: 'Zone tạm',
  capacity_warning: 'Tải cao',
})

export const assignmentWorkspaceWorkloadLabels = Object.freeze({
  unconfigured: 'Chưa đặt tải',
  healthy: 'Bình thường',
  near_capacity: 'Gần đầy',
  over_capacity: 'Vượt tải',
})

export function cleanAssignmentWorkspaceParams(params = {}) {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== undefined && value !== null && value !== '',
    ),
  )
}

export function serializeAssignmentWorkspaceFilters(filters = {}) {
  const normalized = Object.fromEntries(
    Object.entries(filters).filter(
      ([, value]) => value !== undefined && value !== null && value !== '' && value !== 'all',
    ),
  )
  return Object.keys(normalized).length ? JSON.stringify(normalized) : undefined
}

export function createAssignmentWorkspaceResource(method, params = {}) {
  return createResource({
    url: assignmentWorkspaceMethods[method],
    params: cleanAssignmentWorkspaceParams(params),
    auto: false,
  })
}

export function assignmentWorkspaceStatusLabel(status) {
  return assignmentWorkspaceStatusLabels[status] || status || '—'
}

export function assignmentWorkspaceWorkloadLabel(workload) {
  return assignmentWorkspaceWorkloadLabels[workload] || workload || '—'
}

/**
 * Keep the server's parent IDs and revisions intact. The UI only adds a
 * client-side expanded flag; it never invents an assignment relationship.
 */
export function normalizeAssignmentWorkspaceRows(rows = []) {
  const byId = new Map(rows.map((row) => [row.id, row]))
  const children = new Map()

  for (const row of rows) {
    if (!row.parent_id || !byId.has(row.parent_id)) continue
    const siblings = children.get(row.parent_id) || []
    siblings.push(row.id)
    children.set(row.parent_id, siblings)
  }

  return rows.map((row) => ({
    ...row,
    children: children.get(row.id) || [],
    has_children: Boolean(children.get(row.id)?.length || row.has_children),
  }))
}

export function assignmentWorkspaceFilterQuery(filters = {}) {
  return Object.fromEntries(
    Object.entries(filters).filter(
      ([, value]) => value !== undefined && value !== null && value !== '' && value !== 'all',
    ),
  )
}
