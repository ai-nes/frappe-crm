import { describe, expect, it } from 'vitest'
import { roleNavigationTrees } from '../../src/utils/navigationConfig'
import {
  getWorkspaceRoute,
  resolveWorkspaceRoute,
  sanitizeWorkspaceQuery,
  workspaceRegistry,
} from '../../src/utils/workspaceRegistry'

function menuIds(items) {
  return items.flatMap((item) => [item.id, ...menuIds(item.children || [])])
}

describe('workspaceRegistry', () => {
  it('contains each role-navigation item exactly once', () => {
    const ids = Object.values(roleNavigationTrees).flatMap(menuIds)
    expect(new Set(workspaceRegistry.map((entry) => entry.id))).toEqual(
      new Set(ids),
    )
    expect(workspaceRegistry).toHaveLength(ids.length)
  })

  it('resolves only declared workspace and view pairs', () => {
    expect(resolveWorkspaceRoute('sales-records', 'counseling')).toMatchObject({
      id: 'sales_records_counseling',
      capability: 'student.execute',
    })
    expect(resolveWorkspaceRoute('sales-records', 'not-a-view')).toBeNull()
    expect(getWorkspaceRoute('sales_my_records')).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'sales-records', view: 'new' },
    })
    expect(getWorkspaceRoute('sales_lookups')).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'admissions-reference', view: 'programs' },
    })
    expect(getWorkspaceRoute('lead_lookups')).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'admissions-reference', view: 'home' },
    })
    expect(resolveWorkspaceRoute('admissions-reference')).toBeNull()
  })

  it('emits a unique explicit target for every parent entry', () => {
    const targets = workspaceRegistry.filter((entry) => !entry.route.view).map((entry) => {
      const route = getWorkspaceRoute(entry.id)
      return `${route.name}:${route.params.workspace}:${route.params.view}`
    })
    expect(new Set(targets).size).toBe(targets.length)
  })

  it('uses canonical Student workspaces instead of legacy Contact destinations', () => {
    const operationalEntries = workspaceRegistry.filter((entry) =>
      ['sales', 'lead_sales', 'admissions_director'].includes(entry.role),
    )
    expect(
      operationalEntries.every((entry) => entry.page !== 'crm-contact-list'),
    ).toBe(true)
  })

  it('drops query keys that are not part of the workspace contract', () => {
    expect(
      sanitizeWorkspaceQuery('sales-records', 'new', {
        stage: 'MQL',
        owner: 'me',
        unsafe: 'true',
      }),
    ).toEqual({ stage: 'MQL', owner: 'me' })
  })

  it('keeps signed workspace preset keys in the URL contract', () => {
    expect(
      sanitizeWorkspaceQuery('sales-records', 'new', {
        lifecycle: 'Applicant',
        ownership: 'mine',
        documents: 'awaiting',
        unsafe: 'true',
      }),
    ).toEqual({ lifecycle: 'Applicant', ownership: 'mine', documents: 'awaiting' })
  })
})
