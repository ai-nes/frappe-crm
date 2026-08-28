import { describe, expect, it } from 'vitest'
import { getLegacyLeadSalesRoute } from '../../src/utils/leadSalesLegacyRoutes'

describe('getLegacyLeadSalesRoute', () => {
  it.each([
    [{ name: 'Dashboard', query: { section: 'overview' } }, 'Lead Sales Dashboard'],
    [{ name: 'Dashboard', query: { section: 'reports' } }, 'Lead Sales Reports'],
    [{ name: 'CRM Persons', query: {} }, 'Lead Sales Performance'],
    [{ name: 'Tasks', query: {} }, 'Lead Sales Tasks'],
  ])('maps legacy Lead Sales route %#', (route, expectedName) => {
    expect(getLegacyLeadSalesRoute(route)).toEqual({ name: expectedName })
  })

  it('does not retain mappings for removed or unrelated destinations', () => {
    expect(
      getLegacyLeadSalesRoute({
        name: 'Dashboard',
        params: { section: 'overview' },
        query: { scope: 'my' },
      }),
    ).toBeNull()
    expect(
      getLegacyLeadSalesRoute({
        name: 'CRM Contacts',
        query: { filter: 'duplicate' },
      }),
    ).toBeNull()
    expect(
      getLegacyLeadSalesRoute({
        name: 'CRM Contacts',
        query: { stage: 'cold' },
      }),
    ).toBeNull()
    expect(
      getLegacyLeadSalesRoute({
        name: 'Dashboard',
        params: { section: 'sales' },
      }),
    ).toBeNull()
  })
})
