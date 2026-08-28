import { createRouter, createWebHistory } from 'vue-router'
import { usersStore } from '@/stores/users'
import { sessionStore } from '@/stores/session'
import { viewsStore } from '@/stores/views'
import {
  acquisitionWorkspaceCapabilities,
  admissionsWorkspaceCapabilities,
  canAccessWorkspace,
  hasAnyCapability,
} from '@/utils/rolePolicy'
import {
  resolveWorkspaceRoute,
  sanitizeWorkspaceQuery,
} from '@/utils/workspaceRegistry'
import { resolveUserNavigationRole } from '@/utils/navigationConfig'
import { getLegacyLeadSalesRoute } from '@/utils/leadSalesLegacyRoutes'

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
    meta: { anyOf: admissionsWorkspaceCapabilities },
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
    meta: { anyOf: acquisitionWorkspaceCapabilities },
    props: (route) => ({
      dashboardType: 'digital_marketing',
      dashboardSection: route.params.section || 'overview',
    }),
  },
  {
    path: '/dashboard/offline-marketing/:section?',
    name: 'Offline Marketing Dashboard',
    component: () => import('@/pages/Dashboard.vue'),
    meta: { anyOf: acquisitionWorkspaceCapabilities },
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
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    alias: '/tasks',
    path: '/tasks/view/:viewType?',
    name: 'Tasks',
    component: () => import('@/pages/Tasks.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    alias: '/contacts',
    path: '/contacts/view/:viewType?',
    name: 'Contacts',
    component: () => import('@/pages/Contacts.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    path: '/contacts/:contactId',
    name: 'Contact',
    component: () => import(`@/pages/${handleMobileView('Contact')}.vue`),
    meta: { anyOf: admissionsWorkspaceCapabilities },
    props: true,
  },
  {
    alias: '/call-logs',
    path: '/call-logs/view/:viewType?',
    name: 'Call Logs',
    component: () => import('@/pages/CallLogs.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    path: '/crm-students/view/:viewType?',
    name: 'CRM Students',
    component: () => import('@/pages/CRMStudents.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    alias: '/crm-student-sla-attempts',
    path: '/crm-student-sla-attempts/view/:viewType?',
    name: 'CRM Student SLA Attempts',
    component: () => import('@/pages/CRMStudentSLAs.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    path: '/my-recommendations',
    name: 'My Recommendations',
    component: () => import('@/pages/StudentWorklist.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    path: '/lead-sales/dashboard',
    name: 'Lead Sales Dashboard',
    component: () => import('@/pages/LeadSalesDashboard.vue'),
    meta: { anyOf: ['team.oversee'] },
  },
  {
    path: '/lead-sales/performance',
    name: 'Lead Sales Performance',
    component: () => import('@/pages/LeadSalesPerformance.vue'),
    meta: { anyOf: ['team.oversee'] },
  },
  {
    path: '/lead-sales/tasks',
    name: 'Lead Sales Tasks',
    component: () => import('@/pages/LeadSalesTasks.vue'),
    meta: { anyOf: ['team.oversee'] },
  },
  {
    path: '/lead-sales/reports',
    name: 'Lead Sales Reports',
    component: () => import('@/pages/LeadSalesReports.vue'),
    meta: { anyOf: ['team.oversee'] },
  },
  {
    path: '/lead-sales/sla-policies',
    name: 'Lead Sales SLA Policies',
    component: () => import('@/pages/LeadSalesSlaPolicies.vue'),
    meta: { anyOf: ['team.oversee'] },
  },
  {
    path: '/crm-students/:crmStudentId',
    name: 'CRM Student',
    component: () => import('@/pages/CRMStudent.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
    props: true,
  },
  {
    alias: '/crm-contacts',
    path: '/crm-contacts/view/:viewType?',
    name: 'CRM Contacts',
    component: () => import('@/pages/CRMContacts.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    path: '/crm-contacts/:crmContactId',
    name: 'CRM Contact',
    component: () => import('@/pages/CRMContact.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
    props: true,
  },
  {
    alias: '/crm-persons',
    path: '/crm-persons/view/:viewType?',
    name: 'CRM Persons',
    component: () => import('@/pages/CRMPersons.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    path: '/crm-persons/:crmPersonId',
    name: 'CRM Person',
    component: () => import('@/pages/CRMPerson.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
    props: true,
  },
  {
    alias: '/admissions-lookups',
    path: '/lookups',
    name: 'Lookups',
    component: () => import('@/pages/Lookups.vue'),
    meta: {
      anyOf: [
        ...acquisitionWorkspaceCapabilities,
        ...admissionsWorkspaceCapabilities,
      ],
    },
  },
  {
    alias: '/high-schools',
    path: '/high-schools/view/:viewType?',
    name: 'High Schools',
    component: () => import('@/pages/HighSchools.vue'),
    meta: {
      anyOf: [
        ...acquisitionWorkspaceCapabilities,
        ...admissionsWorkspaceCapabilities,
      ],
    },
  },
  {
    path: '/high-schools/:highSchoolId',
    name: 'High School',
    component: () => import('@/pages/HighSchool.vue'),
    meta: {
      anyOf: [
        ...acquisitionWorkspaceCapabilities,
        ...admissionsWorkspaceCapabilities,
      ],
    },
    props: true,
  },
  {
    alias: '/crm-campaigns',
    path: '/crm-campaigns/view/:viewType?',
    name: 'CRM Campaigns',
    component: () => import('@/pages/CRMCampaigns.vue'),
    meta: { anyOf: acquisitionWorkspaceCapabilities },
  },
  {
    path: '/crm-campaigns/:crmCampaignId',
    name: 'CRM Campaign',
    component: () => import('@/pages/CRMCampaign.vue'),
    meta: { anyOf: acquisitionWorkspaceCapabilities },
    props: true,
  },
  {
    alias: '/crm-segments',
    path: '/crm-segments/view/:viewType?',
    name: 'CRM Segments',
    component: () => import('@/pages/CRMSegments.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
  },
  {
    path: '/crm-segments/:crmSegmentId',
    name: 'CRM Segment',
    component: () => import('@/pages/CRMSegment.vue'),
    meta: { anyOf: admissionsWorkspaceCapabilities },
    props: true,
  },
  {
    alias: '/crm-events',
    path: '/crm-events/view/:viewType?',
    name: 'CRM Events',
    component: () => import('@/pages/CRMEvents.vue'),
    meta: { anyOf: acquisitionWorkspaceCapabilities },
  },
  {
    path: '/crm-events/:crmEventId',
    name: 'CRM Event',
    component: () => import('@/pages/CRMEvent.vue'),
    meta: { anyOf: acquisitionWorkspaceCapabilities },
    props: true,
  },
  {
    alias: '/crm-staff',
    path: '/crm-staff/view/:viewType?',
    name: 'CRM Staff',
    component: () => import('@/pages/CRMStaff.vue'),
    meta: { anyOf: ['system.configure'] },
  },
  {
    path: '/data-import',
    name: 'DataImportList',
    component: () => import('@/pages/DataImport.vue'),
    meta: { anyOf: ['system.configure'] },
  },
  {
    path: '/data-import/geography-high-schools',
    name: 'GeographyImport',
    component: () => import('@/pages/GeographyImport.vue'),
    meta: { anyOf: ['system.configure'] },
  },
  {
    path: '/data-import/doctype/:doctype',
    name: 'NewDataImport',
    component: () => import('@/pages/DataImport.vue'),
    meta: { anyOf: ['system.configure'] },
    props: true,
  },
  {
    path: '/data-import/:importName',
    name: 'DataImport',
    component: () => import('@/pages/DataImport.vue'),
    meta: { anyOf: ['system.configure'] },
    props: true,
  },
  {
    path: '/welcome',
    name: 'Welcome',
    component: () => import('@/pages/Welcome.vue'),
  },
  {
    path: '/workspaces/system/:workspace/:view?',
    name: 'System Workspace',
    component: () => import('@/pages/SystemWorkspace.vue'),
    props: (route) => ({
      workspace: resolveWorkspaceRoute(
        route.params.workspace,
        route.params.view,
      ),
    }),
  },
  {
    path: '/workspaces/:workspace/:view?',
    name: 'Role Workspace',
    // The registry guard prevents this shared shell becoming a broad route.
    component: () => import('@/pages/RoleWorkspace.vue'),
    props: (route) => ({
      workspace: resolveWorkspaceRoute(
        route.params.workspace,
        route.params.view,
      ),
    }),
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
  const { users, isCrmUser, getCurrentUser } = usersStore()

  if (isLoggedIn && !users.fetched) {
    try {
      await users.promise
    } catch (error) {
      console.error('Error loading users', error)
    }
  }

  const isWorkspaceRoute = ['Role Workspace', 'System Workspace'].includes(
    to.name,
  )
  const workspaceEntry = isWorkspaceRoute
    ? resolveWorkspaceRoute(to.params.workspace, to.params.view)
    : null

  if (isLoggedIn && isWorkspaceRoute && !workspaceEntry) {
    next({ name: 'Invalid Page' })
    return
  }

  const navigationRole = isLoggedIn
    ? resolveUserNavigationRole(getCurrentUser())
    : null
  if (
    isLoggedIn &&
    [
      'Lead Sales Dashboard',
      'Lead Sales Performance',
      'Lead Sales Tasks',
      'Lead Sales Reports',
      'Lead Sales SLA Policies',
    ].includes(to.name) &&
    navigationRole !== 'lead_sales'
  ) {
    next({ name: 'Not Permitted' })
    return
  }

  const legacyLeadRoute = getLegacyLeadSalesRoute(to)
  if (navigationRole === 'lead_sales' && legacyLeadRoute) {
    next(legacyLeadRoute)
    return
  }

  if (
    isLoggedIn &&
    workspaceEntry &&
    ((workspaceEntry.role === 'system_manager') !==
      (to.name === 'System Workspace') ||
      !canAccessWorkspace(getCurrentUser(), workspaceEntry))
  ) {
    next({ name: 'Not Permitted' })
    return
  }

  if (isLoggedIn && workspaceEntry) {
    const query = sanitizeWorkspaceQuery(
      to.params.workspace,
      to.params.view,
      to.query,
    )
    if (Object.keys(query).length !== Object.keys(to.query).length) {
      next({ name: to.name, params: to.params, query, hash: to.hash })
      return
    }
  }

  const requiredCapabilities = to.meta?.anyOf
  if (
    isLoggedIn &&
    requiredCapabilities &&
    !hasAnyCapability(getCurrentUser(), requiredCapabilities)
  ) {
    next({ name: 'Not Permitted' })
    return
  }

  if (isLoggedIn && to.name !== 'Not Permitted' && !isCrmUser()) {
    next({ name: 'Not Permitted' })
  } else if (to.name === 'Home' && isLoggedIn) {
    const defaultRoute = hasAnyCapability(
      getCurrentUser(),
      admissionsWorkspaceCapabilities,
    )
      ? { name: 'Dashboard' }
      : { name: 'Digital Marketing Dashboard' }
    next(defaultRoute)
    return
  } else if (!isLoggedIn) {
    window.location.href = '/login?redirect-to=/crm'
  } else if (to.matched.length === 0) {
    next({ name: 'Invalid Page' })
  } else if (
    [
      'CRM Student',
      'CRM Contact',
      'CRM Person',
      'High School',
      'CRM Campaign',
      'CRM Event',
    ].includes(to.name) &&
    !to.hash
  ) {
    let storageKey =
      to.name === 'CRM Student'
        ? 'lastCRMStudentTab'
        : to.name === 'CRM Contact'
          ? 'lastCRMContactTab'
          : to.name === 'CRM Person'
            ? 'lastCRMPersonTab'
            : to.name === 'High School'
              ? 'lastHighSchoolTab'
              : to.name === 'CRM Campaign'
                ? 'lastCRMCampaignTab'
                : to.name === 'CRM Event'
                  ? 'lastCRMEventTab'
                  : 'lastActivityTab'
    const defaultTab = to.name === 'CRM Student' ? 'overview' : 'activity'
    const activeTab = localStorage.getItem(storageKey) || defaultTab
    const hash = '#' + activeTab
    next({ ...to, hash })
  } else if (
    [
      'Contacts',
      'Notes',
      'Tasks',
      'Call Logs',
      'CRM Students',
      'CRM Student SLA Attempts',
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
        'CRM Student SLA Attempts': 'CRM Student SLA Attempt',
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
