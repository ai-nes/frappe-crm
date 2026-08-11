import { createRouter, createWebHistory } from 'vue-router'
import { usersStore } from '@/stores/users'
import { sessionStore } from '@/stores/session'
import { viewsStore } from '@/stores/views'

const routes = [
  {
    path: '/',
    name: 'Home',
  },
  {
    path: '/notifications',
    name: 'Notifications',
    component: () => import('@/pages/MobileNotification.vue'),
  },
  {
    path: '/dashboard/sales/:section?',
    alias: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/pages/Dashboard.vue'),
    props: (route) => ({
      dashboardType: 'sales',
      dashboardSection: route.params.section || 'overview',
    }),
  },
  {
    path: '/dashboard/digital-marketing/:section?',
    alias: '/dashboard/marketing/:section?',
    name: 'Digital Marketing Dashboard',
    component: () => import('@/pages/Dashboard.vue'),
    props: (route) => ({
      dashboardType: 'digital_marketing',
      dashboardSection: route.params.section || 'overview',
    }),
  },
  {
    path: '/dashboard/offline-marketing/:section?',
    name: 'Offline Marketing Dashboard',
    component: () => import('@/pages/Dashboard.vue'),
    props: (route) => ({
      dashboardType: 'offline_marketing',
      dashboardSection: route.params.section || 'overview',
    }),
  },
  {
    alias: '/notes',
    path: '/notes/view/:viewType?',
    name: 'Notes',
    component: () => import('@/pages/Notes.vue'),
  },
  {
    alias: '/tasks',
    path: '/tasks/view/:viewType?',
    name: 'Tasks',
    component: () => import('@/pages/Tasks.vue'),
  },
  {
    alias: '/contacts',
    path: '/contacts/view/:viewType?',
    name: 'Contacts',
    component: () => import('@/pages/Contacts.vue'),
  },
  {
    path: '/contacts/:contactId',
    name: 'Contact',
    component: () => import(`@/pages/${handleMobileView('Contact')}.vue`),
    props: true,
  },
  {
    alias: '/call-logs',
    path: '/call-logs/view/:viewType?',
    name: 'Call Logs',
    component: () => import('@/pages/CallLogs.vue'),
  },
  {
    path: '/crm-students/view/:viewType?',
    name: 'CRM Students',
    component: () => import('@/pages/CRMStudents.vue'),
  },
  {
    path: '/crm-students/:crmStudentId',
    name: 'CRM Student',
    component: () => import('@/pages/CRMStudent.vue'),
    props: true,
  },
  {
    alias: '/crm-contacts',
    path: '/crm-contacts/view/:viewType?',
    name: 'CRM Contacts',
    component: () => import('@/pages/CRMContacts.vue'),
  },
  {
    path: '/crm-contacts/:crmContactId',
    name: 'CRM Contact',
    component: () => import('@/pages/CRMContact.vue'),
    props: true,
  },
  {
    alias: '/crm-persons',
    path: '/crm-persons/view/:viewType?',
    name: 'CRM Persons',
    component: () => import('@/pages/CRMPersons.vue'),
  },
  {
    path: '/crm-persons/:crmPersonId',
    name: 'CRM Person',
    component: () => import('@/pages/CRMPerson.vue'),
    props: true,
  },
  {
    alias: '/high-schools',
    path: '/high-schools/view/:viewType?',
    name: 'High Schools',
    component: () => import('@/pages/HighSchools.vue'),
  },
  {
    path: '/high-schools/:highSchoolId',
    name: 'High School',
    component: () => import('@/pages/HighSchool.vue'),
    props: true,
  },
  {
    alias: '/crm-campaigns',
    path: '/crm-campaigns/view/:viewType?',
    name: 'CRM Campaigns',
    component: () => import('@/pages/CRMCampaigns.vue'),
  },
  {
    path: '/crm-campaigns/:crmCampaignId',
    name: 'CRM Campaign',
    component: () => import('@/pages/CRMCampaign.vue'),
    props: true,
  },
  {
    alias: '/crm-events',
    path: '/crm-events/view/:viewType?',
    name: 'CRM Events',
    component: () => import('@/pages/CRMEvents.vue'),
  },
  {
    path: '/crm-events/:crmEventId',
    name: 'CRM Event',
    component: () => import('@/pages/CRMEvent.vue'),
    props: true,
  },
  {
    alias: '/crm-staff',
    path: '/crm-staff/view/:viewType?',
    name: 'CRM Staff',
    component: () => import('@/pages/CRMStaff.vue'),
  },
  {
    path: '/data-import',
    name: 'DataImportList',
    component: () => import('@/pages/DataImport.vue'),
  },
  {
    path: '/data-import/geography-high-schools',
    name: 'GeographyImport',
    component: () => import('@/pages/GeographyImport.vue'),
  },
  {
    path: '/data-import/doctype/:doctype',
    name: 'NewDataImport',
    component: () => import('@/pages/DataImport.vue'),
    props: true,
  },
  {
    path: '/data-import/:importName',
    name: 'DataImport',
    component: () => import('@/pages/DataImport.vue'),
    props: true,
  },
  {
    path: '/welcome',
    name: 'Welcome',
    component: () => import('@/pages/Welcome.vue'),
  },
  {
    path: '/:invalidpath',
    name: 'Invalid Page',
    component: () => import('@/pages/InvalidPage.vue'),
  },
  {
    path: '/not-permitted',
    name: 'Not Permitted',
    component: () => import('@/pages/NotPermitted.vue'),
  },
]

const handleMobileView = (componentName) => {
  return window.innerWidth < 768 ? `Mobile${componentName}` : componentName
}

let router = createRouter({
  history: createWebHistory('/crm'),
  routes,
})

router.beforeEach(async (to, from, next) => {
  router.previousRoute = from

  const { isLoggedIn } = sessionStore()
  const { users, isCrmUser } = usersStore()

  if (isLoggedIn && !users.fetched) {
    try {
      await users.promise
    } catch (error) {
      console.error('Error loading users', error)
    }
  }

  if (isLoggedIn && to.name !== 'Not Permitted' && !isCrmUser()) {
    next({ name: 'Not Permitted' })
  } else if (to.name === 'Home' && isLoggedIn) {
    const { views, getDefaultView } = viewsStore()
    await views.promise

    let defaultView = getDefaultView()
    if (!defaultView) {
      next({ name: 'CRM Students', query: { stage: 'intake' } })
      return
    }

    let { route_name, type, name, is_standard } = defaultView
    route_name = route_name || 'CRM Students'

    if (name && !is_standard) {
      next({
        name: route_name,
        params: { viewType: type },
        query: { view: name },
      })
    } else {
      next({ name: route_name, params: { viewType: type } })
    }
  } else if (!isLoggedIn) {
    window.location.href = '/login?redirect-to=/crm'
  } else if (to.matched.length === 0) {
    next({ name: 'Invalid Page' })
  } else if (
    ['CRM Student', 'CRM Contact', 'CRM Person', 'High School', 'CRM Campaign', 'CRM Event'].includes(to.name) &&
    !to.hash
  ) {
    let storageKey =
      to.name === 'CRM Student' ? 'lastCRMStudentTab'
      : to.name === 'CRM Contact' ? 'lastCRMContactTab'
      : to.name === 'CRM Person' ? 'lastCRMPersonTab'
      : to.name === 'High School' ? 'lastHighSchoolTab'
      : to.name === 'CRM Campaign' ? 'lastCRMCampaignTab'
      : to.name === 'CRM Event' ? 'lastCRMEventTab'
      : 'lastActivityTab'
    const activeTab = localStorage.getItem(storageKey) || 'activity'
    const hash = '#' + activeTab
    next({ ...to, hash })
  } else if (
    [
      'Contacts',
      'Notes',
      'Tasks',
      'Call Logs',
      'CRM Students',
      'CRM Contacts',
      'CRM Persons',
      'High Schools',
      'CRM Campaigns',
      'CRM Events',
      'CRM Staff',
    ].includes(to.name) &&
    !to.query?.view
  ) {
    const { views, standardViews, getDefaultView } = viewsStore()
    await views.promise

    const viewType = to.params?.viewType ?? ''
    const standardViewTypes = ['list', 'kanban', 'group_by']

    if (!viewType) {
      const doctypeMap = {
        Contacts: 'Contact',
        Notes: 'FCRM Note',
        Tasks: 'Task',
        'Call Logs': 'Call Log',
        'CRM Students': 'CRM Student',
        'CRM Contacts': 'CRM Contact',
        'CRM Persons': 'CRM Person',
        'High Schools': 'CRM High School',
        'CRM Campaigns': 'CRM Campaign',
        'CRM Events': 'CRM Event',
        'CRM Staff': 'CRM Staff',
      }

      const doctype = doctypeMap[to.name]
      let defaultViewType = 'list'

      let globalDefault = getDefaultView()
      if (globalDefault && globalDefault.route_name === to.name) {
        defaultViewType = globalDefault.type || 'list'
        if (globalDefault.name && !globalDefault.is_standard) {
          next({
            name: to.name,
            params: { viewType: defaultViewType },
            query: { ...to.query, view: globalDefault.name },
          })
          return
        }
      }

      for (const viewType of standardViewTypes) {
        const standardView = standardViews.value?.[doctype + ' ' + viewType]
        if (standardView?.is_default) {
          defaultViewType = viewType
          break
        }
      }

      next({
        name: to.name,
        params: { viewType: defaultViewType },
        query: to.query,
      })
    } else if (!standardViewTypes.includes(viewType)) {
      const viewNameOrLabel = viewType

      let view = views.data?.find(
        (v) => v.name == viewNameOrLabel || v.label === viewNameOrLabel,
      )

      if (view) {
        next({
          name: to.name,
          params: { viewType: view.type || 'list' },
          query: { ...to.query, view: view.name },
        })
      } else {
        next({
          name: to.name,
          params: { viewType: 'list' },
          query: to.query,
        })
      }
    } else {
      next()
    }
  } else {
    next()
  }
})

export default router
