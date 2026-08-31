import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'src/pages/RoleWorkspace.vue'), 'utf8')
const helperBlock = source.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1]
const { getWorkspaceFilterSchema, normalizeWorkspaceFilters, normalizeWorkspaceResponse, resolveWorkspaceDetail, sameSnapshotMetadata } = new Function(
  `${helperBlock.replaceAll('export ', '')}; return { getWorkspaceFilterSchema, normalizeWorkspaceFilters, normalizeWorkspaceResponse, resolveWorkspaceDetail, sameSnapshotMetadata }`,
)()

describe('Director workspace snapshot coordination', () => {
  const summary = {
    contractStatus: 'ready', snapshot: 'signed-summary',
    snapshotContext: { definitionVersion: 'director-analytics-v1', timezone: 'Asia/Ho_Chi_Minh', asOf: '2026-08-28T00:00:00Z' },
  }

  it('accepts only rows and series bound to the same signed snapshot metadata', () => {
    const payload = { contractStatus: 'ready', snapshot: 'signed-summary', snapshotContext: { ...summary.snapshotContext } }
    expect(sameSnapshotMetadata(summary, payload)).toBe(true)
  })

  it('fails closed when a concurrently loaded dataset has a mismatched snapshot', () => {
    expect(normalizeWorkspaceResponse(summary, { contractStatus: 'ready', snapshot: 'another-snapshot' }, { contractStatus: 'ready', snapshot: 'signed-summary', snapshotContext: { ...summary.snapshotContext } })).toMatchObject({ state: 'unavailable', snapshot: null })
  })

  it('keeps a ready summary visible when an optional rows or series channel is unavailable', () => {
    const response = normalizeWorkspaceResponse(
      { ...summary, kpis: [{ label: 'Students', value: 2 }] },
      { contractStatus: 'migration_required', explanation: 'Rows are not released.' },
      { contractStatus: 'unavailable', explanation: 'Charts are not released.' },
    )
    expect(response).toMatchObject({ contractStatus: 'ready', partial: true, kpis: [{ label: 'Students', value: 2 }] })
    expect(response.state).toBeUndefined()
    expect(response.partialMessage).toContain('Rows are not released.')
    expect(response.partialMessage).toContain('Charts are not released.')
  })

  it('normalizes backend allowed filter descriptors into renderable validated fields', () => {
    const schema = getWorkspaceFilterSchema({ filterSchema: { allowed: ['dateRange', 'campus'] } })
    expect(schema).toEqual([
      { key: 'dateRange', label: 'Date Range', options: [] },
      { key: 'campus', label: 'Campus', options: [] },
    ])
    expect(normalizeWorkspaceFilters(schema, { campus: 'HN', ignored: 'x' })).toEqual({ campus: 'HN' })
  })

  it('preserves a partial summary contract while its channels provide snapshot-bound data', () => {
    const response = normalizeWorkspaceResponse(
      { ...summary, contractStatus: 'partial', availability: { status: 'partial', reason: 'Campaign cost refresh is delayed.' }, kpis: [{ label: 'Students', value: 2 }] },
      { contractStatus: 'ready', snapshot: 'signed-summary', snapshotContext: { ...summary.snapshotContext }, rows: [] },
      { contractStatus: 'ready', snapshot: 'signed-summary', snapshotContext: { ...summary.snapshotContext }, series: [] },
    )
    expect(response.contractStatus).toBe('partial')
    expect(response.kpis).toEqual([{ label: 'Students', value: 2 }])
    expect(response.partialMessage).toContain('Campaign cost refresh is delayed.')
  })

  it('resolves opaque detail tokens server-side before navigating', async () => {
    const request = vi.fn().mockResolvedValue({ route: { name: 'CRM Student', params: { crmStudentId: 'canonical' } } })
    const navigate = vi.fn()
    const context = { workspace: 'director-records', view: 'all', filters: { campus: 'hn' }, snapshot: 'signed-snapshot' }
    await expect(resolveWorkspaceDetail({ resolver: 'crm.api.resolve', token: 'opaque' }, request, navigate, context)).resolves.toBe(true)
    expect(request).toHaveBeenCalledWith('crm.api.resolve', { ...context, token: 'opaque' })
    expect(navigate).toHaveBeenCalledWith({ name: 'CRM Student', params: { crmStudentId: 'canonical' } })
    await expect(resolveWorkspaceDetail({ target: 'raw-id' }, request, navigate)).resolves.toBe(false)
  })
})
