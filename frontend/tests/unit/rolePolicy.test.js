import { describe, expect, it } from 'vitest'
import {
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
      'Events',
    ])
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
    expect(canManageAttribution({ crm_capabilities: ['attribution.manage'] })).toBe(true)
    expect(canManageAttribution({ crm_capabilities: ['acquisition.manage'] })).toBe(false)
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

  it('labels migration state without making it a capability grant', () => {
    expect(roleStateLabel('compatibility_overlay')).toContain('migration')
    expect(roleStateLabel('mixed_or_unmapped')).toContain('review')
    expect(roleStateLabel('canonical_profile')).toBeNull()
  })
})
