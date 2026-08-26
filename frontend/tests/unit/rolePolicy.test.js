import { describe, expect, it } from 'vitest'
import {
  admissionsWorkspaceCapabilities,
  canConfigureSystem,
  canManageAttribution,
  canAccessNavigationRoute,
  canManageRoles,
  hasAnyCapability,
  navigationEntries,
  roleOptionFor,
  roleStateLabel,
  visibleNavigation,
} from '../../src/utils/rolePolicy'

describe('rolePolicy', () => {
  it('denies capability affordances when server data is absent', () => {
    expect(canConfigureSystem()).toBe(false)
    expect(
      visibleNavigation(
        [{ label: 'Settings', capability: 'system.configure' }],
        {},
      ),
    ).toEqual([])
  })

  it('filters navigation from server-derived capabilities only', () => {
    const links = [
      { label: 'Contacts' },
      { label: 'Campaigns', capability: 'acquisition.manage' },
    ]
    expect(
      visibleNavigation(links, { crm_capabilities: ['acquisition.manage'] }),
    ).toEqual(links)
  })

  it('keeps Marketing within the acquisition workspace', () => {
    const marketingNavigation = visibleNavigation(navigationEntries, {
      crm_capabilities: ['acquisition.manage'],
    }).map((entry) => entry.label)

    expect(marketingNavigation).toEqual([
      'Marketing Dashboard',
      'Campaigns',
      'Segments',
      'Events',
    ])
  })

  it('keeps each admissions role within its operational workspace', () => {
    const visibleLabels = (crm_capabilities) =>
      visibleNavigation(navigationEntries, { crm_capabilities }).map(
        (entry) => entry.label,
      )

    expect(
      visibleLabels([
        'student.execute',
        'recommendation.decide',
        'interaction.record',
      ]),
    ).toEqual([
      'My Recommendations',
      'Prospective Students',
      'Contacts',
      'Enrolled Students',
      'Events',
      'Notes',
      'Tasks',
      'Call Logs',
    ])

    expect(
      visibleLabels([
        'student.execute',
        'recommendation.decide',
        'interaction.record',
        'team.oversee',
      ]),
    ).toEqual([
      'Sales Dashboard',
      'My Recommendations',
      'Prospective Students',
      'Contacts',
      'Enrolled Students',
      'High Schools',
      'Persons',
      'Events',
      'Notes',
      'Tasks',
      'Call Logs',
    ])

    expect(
      visibleLabels(['admissions.oversee', 'recommendation.decide']),
    ).toEqual([
      'Sales Dashboard',
      'My Recommendations',
      'Prospective Students',
      'Contacts',
      'Enrolled Students',
      'High Schools',
      'Persons',
      'Events',
      'Notes',
      'Tasks',
      'Call Logs',
    ])
  })

  it('keeps event workflows available while hiding acquisition segmentation', () => {
    const leadSalesUser = {
      crm_capabilities: [
        'student.execute',
        'recommendation.decide',
        'interaction.record',
        'team.oversee',
      ],
    }

    expect(canAccessNavigationRoute(leadSalesUser, 'CRM Segments')).toBe(false)
    expect(canAccessNavigationRoute(leadSalesUser, 'CRM Events')).toBe(true)
    expect(canAccessNavigationRoute(leadSalesUser, 'CRM Students')).toBe(true)
  })

  it('keeps broad route capability separate from sidebar discoverability', () => {
    const saleUser = {
      crm_capabilities: ['student.execute', 'recommendation.decide'],
    }

    expect(hasAnyCapability(saleUser, admissionsWorkspaceCapabilities)).toBe(
      true,
    )
    expect(canAccessNavigationRoute(saleUser, 'High Schools')).toBe(false)
  })

  it('requires one declared capability for role-scoped affordances', () => {
    expect(
      hasAnyCapability({ crm_capabilities: ['student.execute'] }, [
        'acquisition.manage',
        'student.execute',
      ]),
    ).toBe(true)
    expect(
      hasAnyCapability({ crm_capabilities: ['acquisition.manage'] }, [
        'student.execute',
        'admissions.oversee',
      ]),
    ).toBe(false)
  })

  it('filters saved views through the same route affordance policy', () => {
    const marketingUser = { crm_capabilities: ['acquisition.manage'] }
    expect(canAccessNavigationRoute(marketingUser, 'CRM Events')).toBe(true)
    expect(canAccessNavigationRoute(marketingUser, 'CRM Students')).toBe(false)
    expect(canAccessNavigationRoute(marketingUser, 'DataImportList')).toBe(
      false,
    )
  })

  it('uses named system capabilities instead of a profile or raw role guess', () => {
    const systemManager = {
      crm_profile: 'sales',
      crm_capabilities: ['system.configure', 'roles.manage'],
    }
    expect(canConfigureSystem(systemManager)).toBe(true)
    expect(canManageRoles(systemManager)).toBe(true)
    expect(canManageRoles({ crm_capabilities: ['team.oversee'] })).toBe(false)
    expect(
      canManageAttribution({ crm_capabilities: ['attribution.manage'] }),
    ).toBe(true)
    expect(
      canManageAttribution({ crm_capabilities: ['acquisition.manage'] }),
    ).toBe(false)
  })

  it('keeps a shared navigation declaration and canonical selectable roles', () => {
    expect(
      navigationEntries.find((entry) => entry.label === 'Marketing Dashboard'),
    ).toMatchObject({
      to: 'Digital Marketing Dashboard',
      anyOf: ['acquisition.manage', 'system.configure'],
    })
    expect(roleOptionFor('Sale')).toMatchObject({ value: 'Sale' })
    expect(roleOptionFor('Sales')).toBeUndefined()
  })

  it('keeps system managers able to discover every declared module', () => {
    expect(
      visibleNavigation(navigationEntries, {
        crm_capabilities: ['system.configure'],
      }),
    ).toHaveLength(navigationEntries.length)
  })

  it('labels migration state without making it a capability grant', () => {
    expect(roleStateLabel('compatibility_overlay')).toContain('migration')
    expect(roleStateLabel('mixed_or_unmapped')).toContain('review')
    expect(roleStateLabel('canonical_profile')).toBeNull()
  })
})
