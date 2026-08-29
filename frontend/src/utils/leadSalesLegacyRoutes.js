const dashboardSections = Object.freeze({
  overview: 'Lead Sales Dashboard',
  reports: 'Lead Sales Reports',
})

/**
 * Maps only historical Lead Sales destinations to their functional replacements.
 * A caller must still verify that the current user is Lead Sales.
 */
export function getLegacyLeadSalesRoute(to = {}) {
  if (to.name === 'Dashboard') {
    // Lead Sales also retains the personal Sale dashboard.
    if (to.query?.scope === 'my') return null
    const section = to.query?.section || to.params?.section
    const name = dashboardSections[section]
    return name ? { name } : null
  }
  if (to.name === 'CRM Persons' && !to.query?.view) {
    return { name: 'Lead Sales Performance' }
  }
  if (to.name === 'Tasks' && !to.query?.view) {
    return { name: 'Lead Sales Tasks' }
  }
  return null
}
