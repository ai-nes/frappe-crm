import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// Unit tests in this project do not mount Vue SFCs. Evaluate only RoleWorkspace's
// dependency-free helper block so its URL validation is still tested directly.
const source = readFileSync(
  resolve(process.cwd(), 'src/pages/RoleWorkspace.vue'),
  'utf8',
)
const helperBlock = source.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1]
const { getWorkspaceFilterSchema, normalizeWorkspaceFilters, normalizeWorkspaceResponse, workspaceRequest, workspaceState } = new Function(
  `${helperBlock.replaceAll('export ', '')}; return { getWorkspaceFilterSchema, normalizeWorkspaceFilters, normalizeWorkspaceResponse, workspaceRequest, workspaceState }`,
)()

describe('RoleWorkspace shell helpers', () => {
  const schema = [{ key: 'campus', default: 'hn', options: ['hn', 'hcm'] }, { key: 'team', options: ['north'] }]

  it('keeps only validated URL filters and restores defaults', () => {
    expect(normalizeWorkspaceFilters(schema, { campus: 'hcm', team: 'other' })).toEqual({ campus: 'hcm' })
    expect(normalizeWorkspaceFilters(schema, {})).toEqual({ campus: 'hn' })
  })

  it('uses the server filter schema after a ready response', () => {
    const serverSchema = [{ key: 'period', options: ['week', 'month'] }]
    expect(getWorkspaceFilterSchema({ filterSchema: serverSchema }, { filters: schema })).toBe(serverSchema)
    expect(normalizeWorkspaceFilters(serverSchema, { period: 'month' })).toEqual({ period: 'month' })
  })

  it('renders denied and unavailable contract states before ready', () => {
    expect(workspaceState({ status: 403 })).toBe('denied')
    expect(workspaceState({ available: false })).toBe('unavailable')
    expect(workspaceState({ contractStatus: 'unavailable' })).toBe('unavailable')
    expect(workspaceState({ contractStatus: 'migration_required' })).toBe('unavailable')
    expect(workspaceState({ empty: true })).toBe('empty')
    expect(workspaceState({})).toBe('ready')
  })

  it('uses the registry route and default view for reader requests', () => {
    expect(
      workspaceRequest(
        { route: { workspace: 'sales-records', view: null }, defaultView: 'new', preset: { ownership: 'mine' } },
        { campus: 'hn' },
        'signed-snapshot',
      ),
    ).toEqual({
      workspace: 'sales-records',
      view: 'new',
      filters: { ownership: 'mine', campus: 'hn' },
      snapshot: 'signed-snapshot',
    })
    expect(workspaceRequest({}, {})).toBeNull()
  })

  it('does not create shell data when the server contract is unavailable', () => {
    expect(
      normalizeWorkspaceResponse({
        contractStatus: 'migration_required',
        explanation: 'The upstream Student read contract is not released.',
        snapshot: 'signed-snapshot',
        kpis: [{ value: 99 }],
      }),
    ).toEqual({
      contractStatus: 'migration_required',
      state: 'unavailable',
      message: 'The upstream Student read contract is not released.',
      snapshot: 'signed-snapshot',
    })
  })

  it('maps only reader-provided rows and series after a ready summary', () => {
    expect(
      normalizeWorkspaceResponse(
        { contractStatus: 'ready', snapshot: 'signed-snapshot', kpis: [{ key: 'open', value: 2 }] },
        { rows: [{ id: 'STU-1' }], columns: [{ key: 'id', label: 'Student' }], cursor: 'next' },
        { series: [{ period: '2026-08', value: 2 }], definition: 'Open Students' },
      ),
    ).toMatchObject({
      snapshot: 'signed-snapshot',
      kpis: [{ key: 'open', value: 2 }],
      students: { items: [{ id: 'STU-1' }], nextCursor: 'next' },
      analytics: { series: [{ period: '2026-08', value: 2 }], definition: 'Open Students' },
    })
  })
})
