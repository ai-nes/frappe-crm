/**
 * Stable, label-free destinations for role navigation. This is a client
 * discoverability contract only; the workspace reader repeats authorization
 * and scope checks on the server.
 */
const roleCapabilities = {
  sales: 'student.execute',
  lead_sales: 'team.oversee',
  marketing: 'acquisition.manage',
  admissions_director: 'admissions.oversee',
  system_manager: 'system.configure',
}

const queryKeys = [
  'period',
  'campus',
  'team',
  'stage',
  'owner',
  'lifecycle',
  'ownership',
  'urgency',
  'documents',
  'status',
  'tab',
  'page',
  'cursor',
]

const entry = (id, role, workspace, view, page, preset = {}, options = {}) => ({
  id,
  role,
  route: { workspace, view },
  defaultView: options.defaultView,
  capability: options.capability || roleCapabilities[role],
  page,
  preset,
  queryKeys: options.queryKeys || queryKeys,
})

// Parent entries deliberately omit `view`: their defaultView makes the
// default explicit while retaining a unique route declaration per menu ID.
export const workspaceRegistry = [
  entry(
    'sales_immediate_contact',
    'sales',
    'sales-urgent',
    'queue',
    'student-worklist',
    { ownership: 'mine', urgency: 'immediate' },
  ),
  entry(
    'sales_my_records',
    'sales',
    'sales-records',
    null,
    'student-worklist',
    { lifecycle: ['MQL', 'Applicant'], ownership: 'mine' },
    { defaultView: 'new' },
  ),
  entry(
    'sales_records_new',
    'sales',
    'sales-records',
    'new',
    'student-worklist',
    { lifecycle: ['MQL', 'Applicant'], ownership: 'mine' },
  ),
  entry(
    'sales_records_counseling',
    'sales',
    'sales-records',
    'counseling',
    'student-worklist',
    { lifecycle: ['MQL', 'Applicant'], ownership: 'mine' },
  ),
  entry(
    'sales_records_awaiting_docs',
    'sales',
    'sales-records',
    'awaiting-documents',
    'student-worklist',
    { lifecycle: ['Applicant'], ownership: 'mine', documents: 'awaiting' },
  ),
  entry(
    'sales_records_cold',
    'sales',
    'sales-records',
    'cold',
    'student-worklist',
    { ownership: 'mine', lifecycle: ['Cold'] },
  ),
  entry(
    'sales_records_won',
    'sales',
    'sales-records',
    'closed',
    'student-worklist',
    { ownership: 'mine', lifecycle: ['Won'] },
  ),
  entry(
    'sales_unassigned_pool',
    'sales',
    'sales-pool',
    'available',
    'student-worklist',
    { ownership: 'unassigned' },
  ),
  entry('sales_my_tasks', 'sales', 'sales-tasks', 'mine', 'task-worklist', {
    ownership: 'mine',
  }),
  entry(
    'sales_appointments',
    'sales',
    'sales-appointments',
    'calendar',
    'appointment-calendar',
    { ownership: 'mine' },
  ),
  entry(
    'sales_my_results',
    'sales',
    'sales-results',
    'overview',
    'sales-results',
    { ownership: 'mine' },
  ),
  entry(
    'sales_lookups',
    'sales',
    'admissions-reference',
    null,
    'admissions-reference',
    {},
    { defaultView: 'programs' },
  ),

  entry(
    'lead_team_dashboard',
    'lead_sales',
    'team-dashboard',
    'overview',
    'team-dashboard',
  ),
  entry(
    'lead_team_sla',
    'lead_sales',
    'team-sla',
    null,
    'sla-worklist',
    {},
    { defaultView: 'running' },
  ),
  entry(
    'lead_sla_running',
    'lead_sales',
    'team-sla',
    'running',
    'sla-worklist',
  ),
  entry(
    'lead_sla_near_breach',
    'lead_sales',
    'team-sla',
    'near-breach',
    'sla-worklist',
  ),
  entry(
    'lead_sla_breached',
    'lead_sales',
    'team-sla',
    'breached',
    'sla-worklist',
  ),
  entry(
    'lead_sla_violations',
    'lead_sales',
    'team-sla',
    'history',
    'sla-worklist',
  ),
  entry(
    'lead_team_records',
    'lead_sales',
    'team-records',
    null,
    'student-worklist',
    {},
    { defaultView: 'stage' },
  ),
  entry(
    'lead_records_by_stage',
    'lead_sales',
    'team-records',
    'stage',
    'student-worklist',
  ),
  entry(
    'lead_records_by_agent',
    'lead_sales',
    'team-records',
    'owner',
    'student-worklist',
  ),
  entry(
    'lead_records_unassigned',
    'lead_sales',
    'team-records',
    'unowned',
    'student-worklist',
    { ownership: 'unassigned' },
  ),
  entry(
    'lead_records_cold',
    'lead_sales',
    'team-records',
    'cold-abandoned',
    'student-worklist',
    { lifecycle: ['Cold', 'Abandoned'] },
  ),
  entry(
    'lead_assignment',
    'lead_sales',
    'team-assignment',
    'queue',
    'assignment-queue',
  ),
  entry(
    'lead_member_performance',
    'lead_sales',
    'team-performance',
    'members',
    'team-performance',
  ),
  entry('lead_team_tasks', 'lead_sales', 'team-tasks', 'open', 'task-worklist'),
  entry(
    'lead_duplicates',
    'lead_sales',
    'team-duplicates',
    'review',
    'duplicate-review',
  ),
  entry(
    'lead_team_reports',
    'lead_sales',
    'team-reports',
    'overview',
    'team-reports',
  ),
  entry(
    'lead_lookups',
    'lead_sales',
    'admissions-reference',
    null,
    'admissions-reference',
    {},
    { defaultView: 'home' },
  ),
  entry(
    'lead_sla_policy_readonly',
    'lead_sales',
    'sla-policy',
    'read',
    'sla-policy',
  ),

  entry(
    'mkt_overview',
    'marketing',
    'marketing-overview',
    'overview',
    'marketing-dashboard',
  ),
  entry(
    'mkt_cpl',
    'marketing',
    'marketing-overview',
    'cpl',
    'marketing-dashboard',
  ),
  entry(
    'mkt_cpa',
    'marketing',
    'marketing-overview',
    'cpa',
    'marketing-dashboard',
  ),
  entry(
    'mkt_trends',
    'marketing',
    'marketing-overview',
    'weekly-trend',
    'marketing-dashboard',
  ),
  entry(
    'mkt_campaigns',
    'marketing',
    'campaigns',
    null,
    'campaign-worklist',
    {},
    { defaultView: 'active' },
  ),
  entry(
    'mkt_campaigns_running',
    'marketing',
    'campaigns',
    'active',
    'campaign-worklist',
    { status: 'active' },
  ),
  entry(
    'mkt_campaigns_ended',
    'marketing',
    'campaigns',
    'completed',
    'campaign-worklist',
    { status: 'completed' },
  ),
  entry(
    'mkt_campaigns_draft',
    'marketing',
    'campaigns',
    'draft',
    'campaign-worklist',
    { status: 'draft' },
  ),
  entry('mkt_costs', 'marketing', 'campaign-spend', 'mine', 'campaign-spend', {
    ownership: 'mine',
  }),
  entry(
    'mkt_events',
    'marketing',
    'events',
    null,
    'event-worklist',
    {},
    { defaultView: 'upcoming' },
  ),
  entry(
    'mkt_events_upcoming',
    'marketing',
    'events',
    'upcoming',
    'event-worklist',
    { status: 'upcoming' },
  ),
  entry('mkt_events_past', 'marketing', 'events', 'past', 'event-worklist', {
    status: 'past',
  }),
  entry(
    'mkt_events_registrations',
    'marketing',
    'events',
    'registrations',
    'event-worklist',
  ),
  entry(
    'mkt_sources_attribution',
    'marketing',
    'attribution',
    'sources',
    'attribution-dashboard',
  ),
  entry(
    'mkt_funnel',
    'marketing',
    'marketing-funnel',
    'overview',
    'marketing-funnel',
  ),
  entry(
    'mkt_segments_consent',
    'marketing',
    'consent-segments',
    'eligible',
    'consent-segments',
  ),
  entry(
    'mkt_lookups',
    'marketing',
    'admissions-reference',
    'home',
    'admissions-reference',
  ),

  entry(
    'mgr_overview',
    'admissions_director',
    'director-overview',
    'overview',
    'director-dashboard',
  ),
  entry(
    'mgr_progress_quota',
    'admissions_director',
    'director-overview',
    'quota-progress',
    'director-dashboard',
  ),
  entry(
    'mgr_by_campus',
    'admissions_director',
    'director-overview',
    'campus',
    'director-dashboard',
  ),
  entry(
    'mgr_by_major',
    'admissions_director',
    'director-overview',
    'program',
    'director-dashboard',
  ),
  entry(
    'mgr_funnel_forecast',
    'admissions_director',
    'director-forecast',
    'funnel',
    'director-forecast',
  ),
  entry(
    'mgr_sla_system',
    'admissions_director',
    'director-sla',
    null,
    'sla-dashboard',
    {},
    { defaultView: 'team' },
  ),
  entry(
    'mgr_sla_by_team',
    'admissions_director',
    'director-sla',
    'team',
    'sla-dashboard',
  ),
  entry(
    'mgr_sla_by_campus',
    'admissions_director',
    'director-sla',
    'campus',
    'sla-dashboard',
  ),
  entry(
    'mgr_sla_ranking',
    'admissions_director',
    'director-sla',
    'ranking',
    'sla-dashboard',
  ),
  entry(
    'mgr_all_records',
    'admissions_director',
    'director-records',
    'all',
    'student-worklist',
  ),
  entry(
    'mgr_teams_staff',
    'admissions_director',
    'director-people',
    null,
    'people-dashboard',
    {},
    { defaultView: 'team-performance' },
  ),
  entry(
    'mgr_team_perf',
    'admissions_director',
    'director-people',
    'team-performance',
    'people-dashboard',
  ),
  entry(
    'mgr_workload',
    'admissions_director',
    'director-people',
    'workload',
    'people-dashboard',
  ),
  entry(
    'mgr_rebalance',
    'admissions_director',
    'director-people',
    'rebalance',
    'people-dashboard',
  ),
  entry(
    'mgr_marketing_roi',
    'admissions_director',
    'marketing-roi',
    'overview',
    'marketing-roi',
  ),
  entry(
    'mgr_approvals',
    'admissions_director',
    'approvals',
    null,
    'approval-worklist',
    {},
    { defaultView: 'all' },
  ),
  entry(
    'mgr_appr_spend',
    'admissions_director',
    'approvals',
    'spend',
    'approval-worklist',
  ),
  entry(
    'mgr_appr_master_data',
    'admissions_director',
    'approvals',
    'master-data',
    'approval-worklist',
  ),
  entry(
    'mgr_appr_break_glass',
    'admissions_director',
    'approvals',
    'break-glass',
    'approval-worklist',
  ),
  entry(
    'mgr_quota_tuition',
    'admissions_director',
    'admissions-reference',
    'quota-tuition',
    'admissions-reference',
  ),
  entry(
    'mgr_business_config',
    'admissions_director',
    'business-policy',
    null,
    'business-policy',
    {},
    { defaultView: 'sla' },
  ),
  entry(
    'mgr_cfg_sla',
    'admissions_director',
    'business-policy',
    'sla',
    'business-policy',
  ),
  entry(
    'mgr_cfg_distribution',
    'admissions_director',
    'business-policy',
    'distribution',
    'business-policy',
  ),
  entry(
    'mgr_cfg_scoring',
    'admissions_director',
    'business-policy',
    'scoring',
    'business-policy',
  ),
  entry(
    'mgr_reports',
    'admissions_director',
    'embedded-reports',
    'catalog',
    'embedded-reports',
  ),

  entry(
    'adm_users_perms',
    'system_manager',
    'system-identity',
    null,
    'system-identity',
    {},
    { defaultView: 'accounts' },
  ),
  entry(
    'adm_accounts',
    'system_manager',
    'system-identity',
    'accounts',
    'system-identity',
  ),
  entry(
    'adm_roles',
    'system_manager',
    'system-identity',
    'roles',
    'system-identity',
  ),
  entry(
    'adm_access_scopes',
    'system_manager',
    'system-identity',
    'scopes',
    'system-identity',
  ),
  entry(
    'adm_org_structure',
    'system_manager',
    'system-organization',
    null,
    'system-organization',
    {},
    { defaultView: 'campuses' },
  ),
  entry(
    'adm_campus',
    'system_manager',
    'system-organization',
    'campuses',
    'system-organization',
  ),
  entry(
    'adm_teams',
    'system_manager',
    'system-organization',
    'teams',
    'system-organization',
  ),
  entry(
    'adm_staff',
    'system_manager',
    'system-organization',
    'staff',
    'system-organization',
  ),
  entry(
    'adm_integrations',
    'system_manager',
    'system-integrations',
    null,
    'system-integrations',
    {},
    { defaultView: 'telephony' },
  ),
  entry(
    'adm_telephony',
    'system_manager',
    'system-integrations',
    'telephony',
    'system-integrations',
  ),
  entry(
    'adm_zalo_oa',
    'system_manager',
    'system-integrations',
    'zalo',
    'system-integrations',
  ),
  entry(
    'adm_email',
    'system_manager',
    'system-integrations',
    'email',
    'system-integrations',
  ),
  entry(
    'adm_webhook',
    'system_manager',
    'system-integrations',
    'webhooks',
    'system-integrations',
  ),
  entry(
    'adm_api_keys',
    'system_manager',
    'system-api-keys',
    'inventory',
    'system-api-keys',
  ),
  entry(
    'adm_data_model',
    'system_manager',
    'system-data-model',
    'catalog',
    'system-data-model',
  ),
  entry(
    'adm_system_logs',
    'system_manager',
    'system-operations',
    null,
    'system-operations',
    {},
    { defaultView: 'errors' },
  ),
  entry(
    'adm_logs_errors',
    'system_manager',
    'system-operations',
    'errors',
    'system-operations',
  ),
  entry(
    'adm_logs_jobs',
    'system_manager',
    'system-operations',
    'jobs',
    'system-operations',
  ),
  entry(
    'adm_logs_emails',
    'system_manager',
    'system-operations',
    'email-queue',
    'system-operations',
  ),
  entry(
    'adm_backups',
    'system_manager',
    'system-backup',
    'status',
    'system-backup',
  ),
  entry(
    'adm_break_glass',
    'system_manager',
    'system-break-glass',
    'requests',
    'system-break-glass',
  ),
  entry(
    'adm_access_logs',
    'system_manager',
    'system-access-audit',
    'events',
    'system-access-audit',
  ),
]

const entriesById = new Map(workspaceRegistry.map((item) => [item.id, item]))

export function workspaceEntryForMenuId(id) {
  return entriesById.get(id) || null
}

export function resolveWorkspaceRoute(workspace, view) {
  const matches = workspaceRegistry.filter(
    (item) =>
      item.route.workspace === workspace &&
      item.route.view === (view || null),
  )
  // A parent workspace can be shared by roles with different default views.
  // Refuse an implicit default when it is not unique; generated links always
  // include the explicit default below.
  return view || matches.length <= 1 ? matches[0] || null : null
}

export function getWorkspaceRoute(id) {
  const item = workspaceEntryForMenuId(id)
  if (!item) return null

  const name =
    item.role === 'system_manager' ? 'System Workspace' : 'Role Workspace'
  const params = { workspace: item.route.workspace }
  params.view = item.route.view || item.defaultView
  return { name, params }
}

export function sanitizeWorkspaceQuery(workspace, view, query = {}) {
  const item = resolveWorkspaceRoute(workspace, view)
  if (!item) return {}

  return Object.fromEntries(
    Object.entries(query).filter(
      ([key, value]) =>
        item.queryKeys.includes(key) && value != null && value !== '',
    ),
  )
}

export function workspaceCapabilityForRoute(workspace, view) {
  return resolveWorkspaceRoute(workspace, view)?.capability || null
}
