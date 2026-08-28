import { createResource } from 'frappe-ui'
export { formatWorkspaceTimestamp, workspaceDefinition, workspaceKpis, workspaceRows } from './leadSalesWorkspaceAdapters'

const API_PREFIX = 'crm.api.lead_sales_workspace.'

export const leadSalesWorkspaceMethods = Object.freeze({
  dashboard: `${API_PREFIX}get_team_dashboard`,
  performance: `${API_PREFIX}get_member_performance`,
  actions: `${API_PREFIX}list_team_actions`,
  reports: `${API_PREFIX}get_team_reports`,
  policies: `${API_PREFIX}get_readonly_sla_policies`,
})

function cleanParams(params = {}) {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )
}

export function createLeadSalesWorkspaceResource(method, params = {}) {
  return createResource({
    url: leadSalesWorkspaceMethods[method],
    params: cleanParams(params),
    auto: true,
  })
}
