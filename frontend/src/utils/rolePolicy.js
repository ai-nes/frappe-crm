export const canonicalRoleOptions = [
  {
    value: 'Sale',
    label: 'Sale',
    description:
      'Can work with permitted admissions records and private reports.',
  },
  {
    value: 'Marketing',
    label: 'Marketing',
    description: 'Can access permitted campaign and aggregate CRM information.',
  },
  {
    value: 'Promoter',
    label: 'Promoter',
    description: 'Marketing / Offline Marketing role for school relationship activities.',
  },
  {
    value: 'Lead Sale',
    label: 'Lead Sale',
    description:
      'Can access Frappe-granted admissions operations for sales leads.',
  },
  {
    value: 'Admissions Director',
    label: 'Admissions Director',
    description: 'Can access Frappe-granted admissions aggregate information.',
  },
  {
    value: 'System Manager',
    label: 'System Manager',
    description:
      'Can manage all aspects of the CRM, including user management, customizations and settings.',
  },
]

export const admissionsWorkspaceCapabilities = [
  'student.execute',
  'team.oversee',
  'admissions.oversee',
  'system.configure',
]

export const acquisitionWorkspaceCapabilities = [
  'acquisition.manage',
  'system.configure',
]

// Navigation capabilities are intentionally narrower than the route guard
// capabilities above.  The router still protects every admissions route with
// the broad workspace contract; these groups only control discoverability in
// the desktop/mobile sidebars and saved-view affordances.
export const admissionsManagementCapabilities = [
  'team.oversee',
  'admissions.oversee',
  'system.configure',
]

export const admissionsDecisionCapabilities = [
  'recommendation.decide',
  'system.configure',
]

// This declaration controls discoverability only; backend permissions remain authoritative.
export const navigationEntries = [
  {
    label: 'Sales Dashboard',
    icon: 'salesDashboard',
    to: 'Dashboard',
    anyOf: admissionsWorkspaceCapabilities,
  },
  {
    label: 'Marketing Dashboard',
    icon: 'marketingDashboard',
    to: 'Digital Marketing Dashboard',
    anyOf: acquisitionWorkspaceCapabilities,
  },
  {
    label: 'My Recommendations',
    icon: 'recommendations',
    to: 'My Recommendations',
    anyOf: admissionsDecisionCapabilities,
  },
  {
    label: 'Prospective Students',
    icon: 'students',
    to: { name: 'CRM Students', query: { stage: 'intake' } },
    anyOf: admissionsWorkspaceCapabilities,
  },
  {
    label: 'Contacts',
    icon: 'contacts',
    to: 'CRM Contacts',
    anyOf: admissionsWorkspaceCapabilities,
  },
  {
    label: 'Enrolled Students',
    icon: 'enrolledStudents',
    to: { name: 'CRM Students', query: { stage: 'enrolled' } },
    anyOf: admissionsWorkspaceCapabilities,
  },
  {
    label: 'Lookups',
    icon: 'lookups',
    to: 'Lookups',
    anyOf: [...acquisitionWorkspaceCapabilities, ...admissionsWorkspaceCapabilities],
  },
  {
    label: 'Majors & Programs',
    icon: 'majors',
    to: 'CRM Majors',
    anyOf: [...acquisitionWorkspaceCapabilities, ...admissionsWorkspaceCapabilities],
  },
  {
    label: 'High Schools',
    icon: 'schools',
    to: 'High Schools',
    anyOf: [...acquisitionWorkspaceCapabilities, ...admissionsWorkspaceCapabilities],
  },
  {
    label: 'Persons',
    icon: 'persons',
    to: 'CRM Persons',
    anyOf: admissionsManagementCapabilities,
  },
  {
    label: 'Campaigns',
    icon: 'campaigns',
    to: 'CRM Campaigns',
    anyOf: acquisitionWorkspaceCapabilities,
  },
  {
    label: 'Segments',
    icon: 'segments',
    to: 'CRM Segments',
    anyOf: acquisitionWorkspaceCapabilities,
  },
  {
    label: 'Events',
    icon: 'events',
    to: 'CRM Events',
    anyOf: acquisitionWorkspaceCapabilities,
  },
  {
    label: 'Staff',
    icon: 'staff',
    to: 'CRM Staff',
    anyOf: ['system.configure'],
  },
  {
    label: 'Notes',
    icon: 'notes',
    to: 'Notes',
    anyOf: admissionsWorkspaceCapabilities,
  },
  {
    label: 'Tasks',
    icon: 'tasks',
    to: 'Tasks',
    anyOf: admissionsWorkspaceCapabilities,
  },
  {
    label: 'Call Logs',
    icon: 'callLogs',
    to: 'Call Logs',
    anyOf: admissionsWorkspaceCapabilities,
  },
]

export function hasCapability(user, capability) {
  return Boolean(user?.crm_capabilities?.includes(capability))
}

export function hasAnyCapability(user, capabilities) {
  return capabilities.some((capability) => hasCapability(user, capability))
}

// The aggregate task endpoint has its own server-side profile gate. CTV Sale
// is intentionally not granted the broader student.execute capability, so
// this route must preflight against the profile/legacy role instead.
export function canAccessSalesTaskWorkbench(user) {
  const allowedProfiles = ['sales', 'ctv_sale', 'lead_sales']
  const allowedRoles = [
    'Sale',
    'CTV Sale',
    'Lead Sale',
    'CTV-Sale',
    'Sales User',
    'Sales Manager',
    'Team Leader',
  ]
  return Boolean(
    allowedProfiles.includes(user?.crm_profile) ||
    allowedRoles.includes(user?.role) ||
    hasCapability(user, 'system.configure'),
  )
}

/**
 * Frontend preflight only. The workspace reader is the authority for role,
 * team, campus and feature-flag availability; an unavailable response must
 * render its server-provided status rather than unlock a legacy destination.
 */
export function canAccessWorkspace(user, workspaceEntry) {
  return Boolean(
    workspaceEntry?.capability &&
    hasCapability(user, workspaceEntry.capability),
  )
}

export function isWorkspaceContractAvailable(response) {
  return response?.contractStatus === 'ready'
}

export function canAccessNavigationRoute(user, routeName) {
  const entry = navigationEntries.find((item) => {
    const target = item.to
    return target === routeName || target?.name === routeName
  })

  if (!entry) return canConfigureSystem(user)
  return visibleNavigation([entry], user).length > 0
}

export function canConfigureSystem(user) {
  return hasCapability(user, 'system.configure')
}

export function canManageRoles(user) {
  return hasCapability(user, 'roles.manage')
}

// UI affordance only. The attribution command endpoint remains authoritative.
export function canManageAttribution(user) {
  return hasCapability(user, 'attribution.manage')
}

export function roleOptionFor(role) {
  return canonicalRoleOptions.find((option) => option.value === role)
}

export function roleStateLabel(roleState) {
  if (roleState === 'compatibility_overlay')
    return 'Legacy role — migration pending'
  if (roleState === 'legacy_migration_required')
    return 'Legacy role requires migration'
  if (roleState === 'mixed_or_unmapped')
    return 'Role configuration requires review'
  return null
}

export function visibleNavigation(links, user) {
  return links.filter((link) => {
    if (!link.capability && !link.anyOf) return true
    if (link.capability) return hasCapability(user, link.capability)
    return hasAnyCapability(user, link.anyOf)
  })
}
