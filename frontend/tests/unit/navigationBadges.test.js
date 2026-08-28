import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { call } = vi.hoisted(() => ({ call: vi.fn() }))

vi.mock('frappe-ui', () => ({ call }))

import { useNavigationBadgesStore } from '../../src/stores/navigationBadges'

function snapshot(expiresAt) {
  const payload = btoa(JSON.stringify({ expiresAt }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '')
  return `${payload}.signature`
}

describe('navigation badges', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    call.mockReset()
  })

  it('maps ready facade badges to sidebar keys and retains their snapshots', async () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 300
    call.mockResolvedValue({
      contractStatus: 'ready',
      badges: {
        sales_immediate_contact: {
          contractStatus: 'ready',
          count: 3,
          snapshot: snapshot(expiresAt),
          definitionVersion: 'role-workspace-read-v1',
        },
      },
    })
    const store = useNavigationBadgesStore()

    await store.fetchBadges()

    expect(call).toHaveBeenCalledWith('crm.api.role_workspaces.get_workspace_badges')
    expect(store.getBadge('urgentSlaCount')).toBe(3)
    expect(store.badgeSnapshots.urgentSlaCount).toMatchObject({
      workspace: 'sales_immediate_contact',
      snapshot: snapshot(expiresAt),
      expiresAt,
    })
  })

  it('hides unavailable and expired facade badges without using the legacy endpoint', async () => {
    call.mockResolvedValue({
      contractStatus: 'ready',
      badges: {
        sales_immediate_contact: {
          contractStatus: 'ready',
          count: 4,
          snapshot: snapshot(Math.floor(Date.now() / 1000) - 1),
        },
      },
    })
    const store = useNavigationBadgesStore()

    await store.fetchBadges()
    expect(store.getBadge('urgentSlaCount')).toBeNull()

    call.mockResolvedValue({ contractStatus: 'unavailable', badges: {} })
    await store.fetchBadges()
    expect(store.getBadge('urgentSlaCount')).toBeNull()
  })

  it('keeps legacy counters during the default-off workspace dark launch', async () => {
    call.mockResolvedValue({ urgentSlaCount: 2, poolCount: 1 })
    const store = useNavigationBadgesStore()

    await store.fetchBadges(['urgentSlaCount'], false)

    expect(call).toHaveBeenCalledWith('crm.api.dashboard.get_sidebar_badge_counts')
    expect(store.source).toBe('legacy')
    expect(store.getBadge('urgentSlaCount')).toBe(2)
    expect(store.getBadge('poolCount')).toBeNull()
  })
})
