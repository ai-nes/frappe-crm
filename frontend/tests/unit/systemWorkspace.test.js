import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function helpers(path, names) {
  const source = readFileSync(resolve(process.cwd(), path), 'utf8')
  const block = source.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1]
  return new Function('__', `${block.replaceAll('export ', '')}; return { ${names.join(', ')} }`)(
    (value, values = []) => value.replace('{0}', values[0] ?? ''),
  )
}

const { displayStatusIdentity, maskCredential, normalizedStatus, systemActivitySummary } = helpers(
  'src/components/Workspaces/SystemStatusPanel.vue',
  ['displayStatusIdentity', 'maskCredential', 'normalizedStatus', 'systemActivitySummary'],
)
const { organizationMembershipLabel } = helpers('src/components/Workspaces/OrganizationWorkspace.vue', ['organizationMembershipLabel'])
const { systemWorkspaceState } = helpers('src/pages/SystemWorkspace.vue', ['systemWorkspaceState'])

describe('System workspace helpers', () => {
  it('only exposes masked identity values', () => {
    expect(maskCredential('credential-value')).toBe('cr••••ue')
    expect(maskCredential('abcd')).toBe('••••')
    expect(displayStatusIdentity({ endpoint: 'https://provider.example/token-secret' })).toBe('ht••••et')
  })

  it('keeps unknown statuses unavailable and prioritizes failure activity', () => {
    expect(normalizedStatus('unknown')).toBe('unavailable')
    expect(systemActivitySummary({ lastSuccessAt: '10:00', lastFailureAt: '11:00' })).toBe('Last failure: 11:00')
  })

  it('does not invent organization membership counts', () => {
    expect(organizationMembershipLabel({ memberCount: 0 })).toBe('0')
    expect(organizationMembershipLabel({ membershipCount: '2' })).toBe('—')
    expect(organizationMembershipLabel({})).toBe('—')
  })

  it('prioritizes denied and unavailable workspace states', () => {
    expect(systemWorkspaceState({ status: 403 })).toBe('denied')
    expect(systemWorkspaceState({ contractStatus: 'unavailable' })).toBe('unavailable')
    expect(systemWorkspaceState({ state: 'error' })).toBe('error')
    expect(systemWorkspaceState({})).toBe('ready')
  })
})
