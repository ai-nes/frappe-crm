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
    value: 'Lead Sales',
    label: 'Lead Sales',
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
    anyOf: admissionsWorkspaceCapabilities,
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
    to: { name: 'CRM Contacts', query: { stage: 'enrolled' } },
    anyOf: admissionsWorkspaceCapabilities,
  },
  {
    label: 'High Schools',
    icon: 'schools',
    to: 'High Schools',
    anyOf: admissionsWorkspaceCapabilities,
  },
  {
    label: 'Persons',
    icon: 'persons',
    to: 'CRM Persons',
    anyOf: admissionsWorkspaceCapabilities,
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
    anyOf: admissionsWorkspaceCapabilities,
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
