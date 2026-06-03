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
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/pages/Dashboard.vue'),
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
    alias: '/enrollment-students',
    path: '/enrollment-students/view/:viewType?',
    name: 'Enrollment Students',
    component: () => import('@/pages/EnrollmentStudents.vue'),
  },
  {
    path: '/enrollment-students/:enrollmentStudentId',
    name: 'Enrollment Student',
    component: () => import('@/pages/EnrollmentStudent.vue'),
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
    alias: '/persons',
    path: '/persons/view/:viewType?',
    name: 'Persons',
    component: () => import('@/pages/Persons.vue'),
  },
  {
    path: '/persons/:personId',
    name: 'Person',
    component: () => import('@/pages/Person.vue'),
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
    alias: '/campaigns',
    path: '/campaigns/view/:viewType?',
    name: 'Campaigns',
    component: () => import('@/pages/Campaigns.vue'),
  },
  {
    path: '/campaigns/:campaignId',
    name: 'Campaign',
    component: () => import('@/pages/Campaign.vue'),
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
    alias: '/staff',
    path: '/staff/view/:viewType?',
    name: 'Staff',
    component: () => import('@/pages/Staff.vue'),
  },
  {
    path: '/data-import',
    name: 'DataImportList',
    component: () => import('@/pages/DataImport.vue'),
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
      next({ name: 'Enrollment Students', query: { stage: 'intake' } })
      return
    }

    let { route_name, type, name, is_standard } = defaultView
    route_name = route_name || 'Enrollment Students'

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
    ['Enrollment Student', 'CRM Contact', 'Person', 'High School', 'Campaign', 'CRM Event'].includes(to.name) &&
    !to.hash
  ) {
    let storageKey =
      to.name === 'Enrollment Student' ? 'lastEnrollmentStudentTab'
      : to.name === 'CRM Contact' ? 'lastCRMContactTab'
      : to.name === 'Person' ? 'lastPersonTab'
      : to.name === 'High School' ? 'lastHighSchoolTab'
      : to.name === 'Campaign' ? 'lastCampaignTab'
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
      'Enrollment Students',
      'CRM Contacts',
      'Persons',
      'High Schools',
      'Campaigns',
      'CRM Events',
      'Staff',
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
        Tasks: 'CRM Task',
        'Call Logs': 'CRM Call Log',
        'Enrollment Students': 'Enrollment Student',
        'CRM Contacts': 'CRM Contact',
        Persons: 'Person',
        'High Schools': 'CRM High School',
        Campaigns: 'Campaign',
        'CRM Events': 'CRM Event',
        Staff: 'Staff',
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
