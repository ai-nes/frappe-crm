import { defineStore } from 'pinia'
import { ref } from 'vue'
import { call } from 'frappe-ui'

// These are the only facade workspaces that may supply a sidebar badge. They
// deliberately map to navigationConfig's display keys instead of accepting
// arbitrary workspace names returned by the server.
export const workspaceBadgeKeys = {
  sales_immediate_contact: 'urgentSlaCount',
  sales_unassigned_pool: 'poolCount',
  sales_my_tasks: 'myTaskCount',
  lead_team_sla: 'teamSlaBreachedCount',
  lead_assignment: 'unassignedCount',
  lead_duplicates: 'duplicateCount',
  mkt_costs: 'pendingSpendApprovalCount',
  mgr_approvals: 'managerApprovalsCount',
}

const sidebarBadgeKeys = Object.values(workspaceBadgeKeys)

function emptyBadges() {
  return Object.fromEntries(sidebarBadgeKeys.map((key) => [key, null]))
}

function snapshotExpiry(snapshot) {
  if (typeof snapshot !== 'string') return null

  try {
    const payload = snapshot
      .split('.', 1)[0]
      .replace(/-/g, '+')
      .replace(/_/g, '/')
    const padded = payload.padEnd(Math.ceil(payload.length / 4) * 4, '=')
    const expiresAt = JSON.parse(atob(padded)).expiresAt
    return Number.isFinite(expiresAt) ? expiresAt : null
  } catch {
    return null
  }
}

function isAvailable(metadata) {
  return (
    metadata?.contractStatus === 'ready' &&
    Boolean(metadata.snapshot) &&
    Number.isFinite(metadata.expiresAt) &&
    metadata.expiresAt > Date.now() / 1000
  )
}

export const useNavigationBadgesStore = defineStore('navigation-badges', () => {
  const badges = ref(emptyBadges())
  const badgeSnapshots = ref({})
  const source = ref('none')
  const loading = ref(false)

  function clearBadges() {
    badges.value = emptyBadges()
    badgeSnapshots.value = {}
    source.value = 'none'
  }

  async function fetchBadges(allowedBadgeKeys = null, workspaceEnabled = true) {
    loading.value = true
    clearBadges()
    const allowed = allowedBadgeKeys ? new Set(allowedBadgeKeys) : null

    try {
      const endpoint = workspaceEnabled
        ? 'crm.api.role_workspaces.get_workspace_badges'
        : 'crm.api.dashboard.get_sidebar_badge_counts'
      const response = await call(endpoint).catch(() => null)

      if (!workspaceEnabled) {
        if (response && typeof response === 'object' && !response.contractStatus) {
          source.value = 'legacy'
          for (const key of sidebarBadgeKeys) {
            if (allowed && !allowed.has(key)) continue
            const value = response[key]
            badges.value[key] = Number.isFinite(value) && value >= 0 ? value : null
          }
        }
        return
      }

      if (response?.contractStatus !== 'ready' || !response.badges) return
      source.value = 'workspace'

      for (const [workspace, badge] of Object.entries(response.badges)) {
        const key = workspaceBadgeKeys[workspace]
        if (!key || (allowed && !allowed.has(key))) continue

        const expiresAt = badge.expiresAt ?? snapshotExpiry(badge.snapshot)
        badgeSnapshots.value[key] = {
          workspace,
          snapshot: badge.snapshot || null,
          definitionVersion: badge.definitionVersion || null,
          contractStatus: badge.contractStatus || 'unavailable',
          expiresAt,
        }
        badges.value[key] =
          Number.isFinite(badge.count) && badge.count >= 0 ? badge.count : null
      }
    } catch {
      // Keep the sidebar usable while failing closed: legacy global counts are
      // never used as a fallback for workspace-owned destinations.
    } finally {
      loading.value = false
    }
  }

  function getBadge(key) {
    if (!key) return null
    if (source.value === 'legacy') {
      const legacyValue = badges.value[key]
      return legacyValue && legacyValue > 0 ? legacyValue : null
    }
    if (!isAvailable(badgeSnapshots.value[key])) return null
    const value = badges.value[key]
    return value && value > 0 ? value : null
  }

  function setBadge(key, count) {
    if (key in badges.value) badges.value[key] = count
  }

  return {
    badges,
    badgeSnapshots,
    source,
    loading,
    fetchBadges,
    getBadge,
    setBadge,
  }
})
