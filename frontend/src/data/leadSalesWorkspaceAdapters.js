export function workspaceRows(payload, key) {
  return Array.isArray(payload?.[key]) ? payload[key] : []
}

export function workspaceKpis(payload) {
  const kpis = payload?.kpis
  if (Array.isArray(kpis)) return kpis
  if (!kpis || typeof kpis !== 'object') return []
  const labels = {
    active_students: __('Hồ sơ đang xử lý'),
    unassigned_students: __('Hồ sơ chưa phân công'),
    breached_sla: __('SLA đã trễ'),
  }
  return Object.entries(kpis).map(([key, value]) => ({ key, label: labels[key] || key, value }))
}

export function workspaceDefinition(payload) {
  const definition = payload?.definition
  if (!definition) return ''
  if (typeof definition === 'string') return definition
  return definition.scope ? __('Phạm vi hồ sơ hiện tại của nhóm') : ''
}

export function formatWorkspaceTimestamp(payload) {
  return payload?.generatedAt || payload?.generated_at || ''
}
