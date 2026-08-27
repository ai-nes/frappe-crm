import { defineStore } from 'pinia'
import { ref } from 'vue'
import { call } from 'frappe-ui'

export const useNavigationBadgesStore = defineStore('navigation-badges', () => {
  const badges = ref({
    urgentSlaCount: 0,
    poolCount: 0,
    teamSlaBreachedCount: 0,
    unassignedCount: 0,
    duplicateCount: 0,
    pendingSpendApprovalCount: 0,
    managerApprovalsCount: 0,
    myTaskCount: 0,
  })

  const loading = ref(false)

  async function fetchBadges() {
    loading.value = true
    try {
      const res = await call('crm.api.dashboard.get_sidebar_badge_counts').catch(() => null)
      if (res) {
        Object.assign(badges.value, res)
      }
    } catch {
      // Graceful fallback without throwing
    } finally {
      loading.value = false
    }
  }

  function getBadge(key) {
    if (!key) return null
    const val = badges.value[key]
    return val && val > 0 ? val : null
  }

  function setBadge(key, count) {
    if (key in badges.value) {
      badges.value[key] = count
    }
  }

  return {
    badges,
    loading,
    fetchBadges,
    getBadge,
    setBadge,
  }
})

