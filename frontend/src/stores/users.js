import { defineStore } from 'pinia'
import { createResource } from 'frappe-ui'
import { sessionStore } from './session'
import { computed, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { canConfigureSystem, hasCapability } from '@/utils/rolePolicy'

export const usersStore = defineStore('crm-users', () => {
  const session = sessionStore()

  let usersByName = reactive({})
  const router = useRouter()

  const users = createResource({
    url: 'crm.api.session.get_users',
    cache: 'crm-users',
    initialData: [],
    auto: true,
    transform([allUsers, crmUsers]) {
      for (let user of allUsers) {
        usersByName[user.name] = user
        if (user.name === 'Administrator') {
          usersByName[user.email] = user
        }
      }
      return { allUsers, crmUsers }
    },
    onError(error) {
      if (error && error.exc_type === 'AuthenticationError') {
        router.push('/login')
      }
    },
  })

  function getUser(email) {
    if (!email || email === 'sessionUser') {
      email = session.user
    }
    if (!usersByName[email]) {
      usersByName[email] = {
        name: email,
        email: email,
        full_name: email.split('@')[0],
        first_name: email.split('@')[0],
        last_name: '',
        user_image: null,
        role: null,
        language: 'vi',
      }
    }
    return usersByName[email]
  }

  function isAdmin(email) {
    return canConfigureSystem(getUser(email))
  }

  function isManager(email) {
    // Deprecated compatibility adapter for legacy callers. New UI names the
    // capability it requires instead of treating supervisors as administrators.
    return isAdmin(email)
  }

  function isWebsiteUser(email) {
    return getUser(email).user_type === 'Website User'
  }

  function isSalesUser(email) {
    return getUser(email).crm_profile === 'sales'
  }

  function getCurrentUser() {
    return getUser()
  }

  function getCrmProfile(email) {
    return getUser(email).crm_profile || null
  }

  function getCrmRoleState(email) {
    return getUser(email).crm_role_state || null
  }

  function hasCrmCapability(capability, email) {
    return hasCapability(getUser(email), capability)
  }

  function isTelephonyAgent(email) {
    return getUser(email).is_telphony_agent
  }

  function getUserRole(email) {
    const user = getUser(email)
    if (user && user.role) {
      return user.role
    }
    return null
  }

  const isCrmUser = (user) => {
    user = user || session.user
    return users.data.crmUsers?.find((u) => u.name === user)
  }

  return {
    users,
    allUsers: computed(() => users.data.allUsers),
    crmUsers: computed(() => users.data.crmUsers),
    getUser,
    getCurrentUser,
    getCrmProfile,
    getCrmRoleState,
    hasCrmCapability,
    isAdmin,
    isManager,
    isSalesUser,
    isTelephonyAgent,
    getUserRole,
    isWebsiteUser,
    isCrmUser,
  }
})
