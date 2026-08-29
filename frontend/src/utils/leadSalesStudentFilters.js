const LEAD_SALES_STUDENT_CONTEXTS = Object.freeze({
  by_stage: Object.freeze({ bypassFunnel: true, filters: {} }),
  by_agent: Object.freeze({
    bypassFunnel: true,
    defaultGroupByField: 'owner_staff',
    filters: {},
  }),
  unassigned: Object.freeze({
    bypassFunnel: true,
    filters: { owner_staff: ['is', 'not set'] },
  }),
  // Cold/abandoned is an outcome-stream concept, not a lifecycle stage. Its
  // legacy entry is replaced by an unavailable state in Phase 2, but keeping
  // this marker explicit prevents a direct URL from silently meaning "Lost".
  cold_abandoned: Object.freeze({ temporary: true, filters: {} }),
})

export function getLeadSalesStudentContext(query = {}) {
  const context = LEAD_SALES_STUDENT_CONTEXTS[query.lead_view]
  if (!context) return {}

  return {
    ...context,
    filters: { ...context.filters },
  }
}

export function getLeadSalesStudentFilters(query = {}) {
  return getLeadSalesStudentContext(query).filters || {}
}
