/**
 * Role-based navigation structure according to role-navigation-menu-structure.md
 */

import { getWorkspaceRoute } from '@/utils/workspaceRegistry'
import { showSettings, activeSettingsPage } from '@/composables/settings'

const rawRoleNavigationTrees = {
  // 1. Sales — Tư vấn viên
  sales: [
    {
      id: 'sales_my_results',
      label: 'Dashboard',
      icon: 'layout-dashboard',
      to: {
        name: 'Dashboard',
        params: { section: 'overview' },
        query: { scope: 'my' },
      },
    },
    {
      id: 'sales_immediate_contact',
      label: 'Cần liên hệ ngay',
      icon: 'flame',
      to: 'My Recommendations',
      badgeKey: 'urgentSlaCount',
      badgeVariant: 'red',
    },
    {
      id: 'sales_my_records',
      label: 'Lead',
      icon: 'clipboard-list',
      to: { name: 'CRM Students', params: { viewType: 'list' } },
      children: [
        {
          id: 'sales_records_new',
          label: 'Mới',
          to: { name: 'CRM Students', query: { sales_view: 'new' } },
        },
        {
          id: 'sales_records_counseling',
          label: 'Đang tư vấn',
          to: { name: 'CRM Students', query: { sales_view: 'counseling' } },
        },
        {
          id: 'sales_records_awaiting_docs',
          label: 'Chờ hồ sơ',
          to: { name: 'CRM Students', query: { sales_view: 'awaiting_docs' } },
        },
        {
          id: 'sales_records_cold',
          label: 'Chưa chăm sóc',
          to: { name: 'CRM Students', query: { sales_view: 'cold' } },
        },
        {
          id: 'sales_records_won',
          label: 'Đã chuyển đổi',
          to: { name: 'CRM Students', query: { sales_view: 'won' } },
        },
        {
          id: 'sales_unassigned_pool',
          label: 'Chưa phân công',
          to: { name: 'CRM Students', query: { sales_view: 'unassigned' } },
        },
      ],
    },
    {
      id: 'sales_my_tasks',
      label: 'Việc của tôi',
      icon: 'list-checks',
      to: 'CTV Sale Tasks',
      badgeKey: 'myTaskCount',
    },
    {
      id: 'sales_appointments',
      label: 'Lịch hẹn',
      icon: 'calendar',
      to: 'Call Logs',
    },
    {
      id: 'sales_lookups',
      label: 'Tra cứu',
      icon: 'book-open',
      to: 'Lookups',
    },
  ],

  // 2. Lead Sales — Trưởng nhóm
  lead_sales: [
    {
      id: 'lead_sales_dashboard',
      label: 'Dashboard Sale',
      icon: 'layout-dashboard',
      to: {
        name: 'Dashboard',
        params: { section: 'overview' },
        query: { scope: 'my' },
      },
    },
    {
      id: 'lead_team_dashboard',
      label: 'Bảng điều khiển nhóm',
      icon: 'layout-dashboard',
      to: 'Lead Sales Dashboard',
    },
    {
      id: 'lead_team_sla',
      label: 'SLA nhóm',
      icon: 'clock',
      to: 'CRM Student SLA Attempts',
      children: [
        {
          id: 'lead_sla_running',
          label: 'Đang chạy',
          to: {
            name: 'CRM Student SLA Attempts',
            query: { tab: 'running' },
          },
        },
        {
          id: 'lead_sla_near_breach',
          label: 'Sắp trễ (<30 phút)',
          to: {
            name: 'CRM Student SLA Attempts',
            query: { tab: 'near_breach' },
          },
        },
        {
          id: 'lead_sla_breached',
          label: 'Đã trễ',
          to: {
            name: 'CRM Student SLA Attempts',
            query: { tab: 'breached' },
          },
          badgeKey: 'teamSlaBreachedCount',
          badgeVariant: 'red',
        },
        {
          id: 'lead_sla_violations',
          label: 'Lịch sử vi phạm',
          to: {
            name: 'CRM Student SLA Attempts',
            query: { tab: 'history' },
          },
        },
      ],
    },
    {
      id: 'lead_team_records',
      label: 'Hồ sơ nhóm',
      icon: 'users',
      to: { name: 'CRM Students', query: { lead_view: 'by_stage' } },
      children: [
        {
          id: 'lead_records_by_stage',
          label: 'Theo giai đoạn',
          to: {
            name: 'CRM Students',
            params: { viewType: 'list' },
            query: { lead_view: 'by_stage' },
          },
        },
        {
          id: 'lead_records_by_agent',
          label: 'Theo tư vấn viên',
          to: {
            name: 'CRM Students',
            params: { viewType: 'group_by' },
            query: { lead_view: 'by_agent' },
          },
        },
        {
          id: 'lead_records_unassigned',
          label: 'Không có chủ sở hữu',
          to: {
            name: 'CRM Students',
            query: { owner: 'unassigned', lead_view: 'unassigned' },
          },
        },
      ],
    },
    {
      id: 'lead_assignment',
      label: 'Hồ sơ chưa phân công',
      icon: 'git-fork',
      to: {
        name: 'CRM Students',
        query: { owner: 'unassigned', lead_view: 'unassigned' },
      },
    },
    {
      id: 'lead_assignment_overview',
      label: 'Cơ chế phân bổ',
      icon: 'settings-2',
      direct: true,
      to: 'Assignment Overview',
    },
    {
      id: 'lead_member_performance',
      label: 'Hiệu suất thành viên',
      icon: 'user-check',
      to: 'Lead Sales Performance',
    },
    {
      id: 'lead_team_tasks',
      label: 'Việc nhóm',
      icon: 'list-checks',
      to: 'Lead Sales Tasks',
    },
    {
      id: 'lead_team_reports',
      label: 'Báo cáo nhóm',
      icon: 'bar-chart-3',
      to: 'Lead Sales Reports',
    },
    {
      id: 'lead_lookups',
      label: 'Tra cứu',
      icon: 'book-open',
      to: 'Lookups',
    },
    {
      id: 'lead_sla_policy_readonly',
      label: 'Chính sách SLA (chỉ đọc)',
      icon: 'shield-check',
      to: 'Lead Sales SLA Policies',
    },
  ],

  // 3. Marketing
  marketing: [
    {
      id: 'mkt_overview',
      label: 'Tổng quan marketing',
      icon: 'line-chart',
      to: {
        name: 'Digital Marketing Dashboard',
        params: { section: 'overview' },
      },
      children: [
        {
          id: 'mkt_cpl',
          label: 'CPL theo kênh',
          to: {
            name: 'Digital Marketing Dashboard',
            params: { section: 'cpl' },
          },
        },
        {
          id: 'mkt_cpa',
          label: 'CPA (chi phí / học sinh)',
          to: {
            name: 'Digital Marketing Dashboard',
            params: { section: 'cpa' },
          },
        },
        {
          id: 'mkt_trends',
          label: 'Xu hướng theo tuần',
          to: {
            name: 'Digital Marketing Dashboard',
            params: { section: 'trends' },
          },
        },
      ],
    },
    {
      id: 'mkt_campaigns',
      label: 'Chiến dịch',
      icon: 'megaphone',
      to: 'CRM Campaigns',
      children: [
        {
          id: 'mkt_campaigns_running',
          label: 'Đang chạy',
          to: { name: 'CRM Campaigns', query: { status: 'Active' } },
        },
        {
          id: 'mkt_campaigns_ended',
          label: 'Đã kết thúc',
          to: { name: 'CRM Campaigns', query: { status: 'Completed' } },
        },
        {
          id: 'mkt_campaigns_draft',
          label: 'Nháp',
          to: { name: 'CRM Campaigns', query: { status: 'Draft' } },
        },
      ],
    },
    {
      id: 'mkt_costs',
      label: 'Chi phí',
      icon: 'coins',
      to: { name: 'CRM Campaigns', query: { view: 'spend' } },
      badgeKey: 'pendingSpendApprovalCount',
      badgeVariant: 'orange',
    },
    {
      id: 'mkt_events',
      label: 'Sự kiện tuyển sinh',
      icon: 'calendar',
      to: 'CRM Events',
      children: [
        {
          id: 'mkt_events_upcoming',
          label: 'Sắp diễn ra',
          to: { name: 'CRM Events', query: { status: 'Upcoming' } },
        },
        {
          id: 'mkt_events_past',
          label: 'Đã diễn ra',
          to: { name: 'CRM Events', query: { status: 'Past' } },
        },
        {
          id: 'mkt_events_registrations',
          label: 'Đăng ký tham dự',
          to: { name: 'CRM Events', query: { tab: 'registrations' } },
        },
      ],
    },
    {
      id: 'mkt_sources_attribution',
      label: 'Nguồn & Attribution',
      icon: 'search',
      to: {
        name: 'Digital Marketing Dashboard',
        params: { section: 'attribution' },
      },
    },
    {
      id: 'mkt_funnel',
      label: 'Phễu chuyển đổi',
      icon: 'filter',
      to: {
        name: 'Digital Marketing Dashboard',
        params: { section: 'funnel' },
      },
    },
    {
      id: 'mkt_segments_consent',
      label: 'Danh sách gửi (theo consent)',
      icon: 'send',
      to: 'CRM Segments',
    },
    {
      id: 'mkt_lookups',
      label: 'Tra cứu',
      icon: 'book-open',
      to: 'High Schools',
    },
  ],

  // 4. Manager — Giám đốc tuyển sinh
  admissions_director: [
    {
      id: 'mgr_overview',
      label: 'Tổng quan tuyển sinh',
      icon: 'target',
      to: { name: 'Dashboard', params: { section: 'overview' } },
      children: [
        {
          id: 'mgr_progress_quota',
          label: 'Tiến độ so với chỉ tiêu',
          to: { name: 'Dashboard', params: { section: 'quota_progress' } },
        },
        {
          id: 'mgr_by_campus',
          label: 'Theo campus',
          to: { name: 'Dashboard', params: { section: 'campus' } },
        },
        {
          id: 'mgr_by_major',
          label: 'Theo ngành',
          to: { name: 'Dashboard', params: { section: 'majors' } },
        },
      ],
    },
    {
      id: 'mgr_funnel_forecast',
      label: 'Phễu & Dự báo',
      icon: 'line-chart',
      to: { name: 'Dashboard', params: { section: 'funnel_forecast' } },
    },
    {
      id: 'mgr_sla_system',
      label: 'SLA toàn hệ',
      icon: 'clock',
      to: 'CRM Student SLA Attempts',
      children: [
        {
          id: 'mgr_sla_by_team',
          label: 'Theo nhóm',
          to: {
            name: 'CRM Student SLA Attempts',
            query: { tab: 'running' },
          },
        },
        {
          id: 'mgr_sla_by_campus',
          label: 'Theo campus',
          to: {
            name: 'CRM Student SLA Attempts',
            query: { tab: 'near_breach' },
          },
        },
        {
          id: 'mgr_sla_ranking',
          label: 'Xếp hạng vi phạm',
          to: {
            name: 'CRM Student SLA Attempts',
            query: { tab: 'breached' },
          },
        },
      ],
    },
    {
      id: 'mgr_all_records',
      label: 'Hồ sơ (toàn bộ)',
      icon: 'clipboard-list',
      to: 'CRM Contacts',
    },
    {
      id: 'mgr_teams_staff',
      label: 'Nhóm & Nhân sự',
      icon: 'users',
      to: { name: 'Dashboard', params: { section: 'team_management' } },
      children: [
        {
          id: 'mgr_team_perf',
          label: 'Hiệu suất theo nhóm',
          to: { name: 'Dashboard', params: { section: 'team_performance' } },
        },
        {
          id: 'mgr_workload',
          label: 'Tải công việc',
          to: { name: 'Dashboard', params: { section: 'workload' } },
        },
        {
          id: 'mgr_rebalance',
          label: 'Phân bổ lại',
          to: { name: 'CRM Contacts', query: { reassign: '1' } },
        },
      ],
    },
    {
      id: 'mgr_marketing_roi',
      label: 'Marketing ROI',
      icon: 'pie-chart',
      to: { name: 'Digital Marketing Dashboard', params: { section: 'roi' } },
    },
    {
      id: 'mgr_approvals',
      label: 'Chờ duyệt',
      icon: 'pen-tool',
      to: { name: 'CRM Campaigns', query: { tab: 'approvals' } },
      badgeKey: 'managerApprovalsCount',
      badgeVariant: 'orange',
      children: [
        {
          id: 'mgr_appr_spend',
          label: 'Chi phí chiến dịch',
          to: { name: 'CRM Campaigns', query: { tab: 'spend_approvals' } },
        },
        {
          id: 'mgr_appr_master_data',
          label: 'Thay đổi master data',
          to: { name: 'DataImportList', query: { type: 'approvals' } },
        },
        {
          id: 'mgr_appr_break_glass',
          label: 'Yêu cầu Break Glass',
          to: { name: 'Dashboard', query: { approvals: 'break_glass' } },
        },
      ],
    },
    {
      id: 'mgr_quota_tuition',
      label: 'Chỉ tiêu & Học phí',
      icon: 'graduation-cap',
      to: 'DataImportList',
    },
    {
      id: 'mgr_business_config',
      label: 'Cấu hình nghiệp vụ',
      icon: 'sliders',
      action: () => {
        showSettings.value = true
        activeSettingsPage.value = 'SLA Policies'
      },
      children: [
        {
          id: 'mgr_cfg_sla',
          label: 'Chính sách SLA',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'SLA Policies'
          },
        },
        {
          id: 'mgr_cfg_distribution',
          label: 'Chính sách phân phối',
          direct: true,
          to: 'Assignment Overview',
        },
        {
          id: 'mgr_cfg_scoring',
          label: 'Mô hình chấm điểm',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'Categories'
          },
        },
      ],
    },
    {
      id: 'mgr_reports',
      label: 'Báo cáo (Metabase)',
      icon: 'bar-chart-2',
      to: { name: 'Dashboard', params: { section: 'reports' } },
    },
  ],

  // 5. Admin — Kỹ thuật
  system_manager: [
    {
      id: 'adm_users_perms',
      label: 'Người dùng & Phân quyền',
      icon: 'user-cog',
      action: () => {
        showSettings.value = true
        activeSettingsPage.value = 'Users'
      },
      children: [
        {
          id: 'adm_accounts',
          label: 'Tài khoản',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'Users'
          },
        },
        {
          id: 'adm_roles',
          label: 'Vai trò',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'Users'
          },
        },
        {
          id: 'adm_access_scopes',
          label: 'Phạm vi truy cập',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'Preferences'
          },
        },
      ],
    },
    {
      id: 'adm_org_structure',
      label: 'Cơ cấu tổ chức',
      icon: 'building',
      to: 'CRM Staff',
      children: [
        {
          id: 'adm_campus',
          label: 'Campus',
          to: 'GeographyImport',
        },
        {
          id: 'adm_teams',
          label: 'Nhóm',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'Assignment Rules'
          },
        },
        {
          id: 'adm_staff',
          label: 'Nhân sự (Staff)',
          to: 'CRM Staff',
        },
        {
          id: 'adm_assignment_overview',
          label: 'Cơ chế phân bổ',
          direct: true,
          to: 'Assignment Overview',
        },
      ],
    },
    {
      id: 'adm_integrations',
      label: 'Tích hợp',
      icon: 'plug',
      action: () => {
        showSettings.value = true
        activeSettingsPage.value = 'Telephony'
      },
      children: [
        {
          id: 'adm_telephony',
          label: 'Tổng đài',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'Telephony'
          },
        },
        {
          id: 'adm_zalo_oa',
          label: 'Zalo OA / WhatsApp',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'WhatsApp'
          },
        },
        {
          id: 'adm_email',
          label: 'Email',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'Accounts'
          },
        },
        {
          id: 'adm_webhook',
          label: 'Webhook',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'General'
          },
        },
      ],
    },
    {
      id: 'adm_api_keys',
      label: 'API Key',
      icon: 'key',
      action: () => {
        showSettings.value = true
        activeSettingsPage.value = 'General'
      },
    },
    {
      id: 'adm_data_model',
      label: 'Mô hình dữ liệu',
      icon: 'database',
      to: 'DataImportList',
    },
    {
      id: 'adm_system_logs',
      label: 'Nhật ký hệ thống',
      icon: 'activity',
      action: () => {
        showSettings.value = true
        activeSettingsPage.value = 'General'
      },
      children: [
        {
          id: 'adm_logs_errors',
          label: 'Lỗi',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'General'
          },
        },
        {
          id: 'adm_logs_jobs',
          label: 'Hàng đợi công việc',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'General'
          },
        },
        {
          id: 'adm_logs_emails',
          label: 'Hàng đợi email',
          action: () => {
            showSettings.value = true
            activeSettingsPage.value = 'Accounts'
          },
        },
      ],
    },
    {
      id: 'adm_backups',
      label: 'Sao lưu',
      icon: 'hard-drive',
      action: () => {
        showSettings.value = true
        activeSettingsPage.value = 'Defaults'
      },
    },
    {
      id: 'adm_break_glass',
      label: 'Break Glass (quyền tạm)',
      icon: 'lock',
      action: () => {
        showSettings.value = true
        activeSettingsPage.value = 'Preferences'
      },
    },
    {
      id: 'adm_access_logs',
      label: 'Nhật ký truy cập',
      icon: 'eye',
      action: () => {
        showSettings.value = true
        activeSettingsPage.value = 'General'
      },
    },
  ],
}

function bindWorkspaceDestinations(items) {
  return items.map((source) => {
    const { children, ...item } = source
    delete item.action
    return {
      ...item,
      // The aggregate task workbench is a named route shared by Sale and CTV Sale.
      to:
        item.direct || item.id === 'sales_my_tasks'
          ? item.to
          : getWorkspaceRoute(item.id),
      ...(children && { children: bindWorkspaceDestinations(children) }),
    }
  })
}

const directorWorkspaceMenuIds = new Set([
  'mgr_overview',
  'mgr_progress_quota',
  'mgr_by_campus',
  'mgr_by_major',
  'mgr_all_records',
  'mgr_funnel_forecast',
  'mgr_sla_system',
  'mgr_sla_by_team',
  'mgr_sla_by_campus',
  'mgr_sla_ranking',
  'mgr_teams_staff',
  'mgr_team_perf',
  'mgr_workload',
  'mgr_rebalance',
  'mgr_marketing_roi',
  'mgr_approvals',
  'mgr_appr_spend',
  'mgr_appr_master_data',
  'mgr_appr_break_glass',
  'mgr_quota_tuition',
  'mgr_reports',
])

function bindDirectorWorkspaceDestinations(items) {
  return items.map((item) => ({
    ...item,
    ...(directorWorkspaceMenuIds.has(item.id) && {
      to: getWorkspaceRoute(item.id),
    }),
    ...(item.children && {
      children: bindDirectorWorkspaceDestinations(item.children),
    }),
  }))
}

// Every role menu opens a named workspace. Legacy Dashboard, CRM Contact and
// Settings-modal shortcuts are intentionally not retained for operational use.
export const roleNavigationTrees = Object.fromEntries(
  Object.entries(rawRoleNavigationTrees).map(([role, items]) => [
    role,
    bindWorkspaceDestinations(items),
  ]),
)

/**
 * The workspace reader is dark-launched server-side. Keep existing menu
 * destinations until the session has received an explicit, server-issued
 * rollout flag; a missing flag must never turn a normal CRM click into an
 * unavailable workspace.
 */
export function isRoleWorkspaceNavigationEnabled(user) {
  return user?.crm_feature_flags?.role_workspace_read === true
}

export function isDirectorWorkspaceNavigationEnabled(user) {
  // A Director destination must never fall back to the unrelated Sales
  // dashboard. The workspace owns its own empty/unavailable state.
  return resolveUserNavigationRole(user) === 'admissions_director'
}

/**
 * Resolves the primary role/profile key for a user object.
 */
export function resolveUserNavigationRole(user) {
  if (!user) return 'sales'

  if (
    user.role === 'System Manager' ||
    user.crm_role_state === 'platform_superuser' ||
    user.crm_capabilities?.includes('system.configure')
  ) {
    return 'system_manager'
  }

  if (user.crm_profile === 'lead_sales' || user.role === 'Lead Sales') {
    return 'lead_sales'
  }

  if (user.crm_profile === 'marketing' || user.role === 'Marketing') {
    return 'marketing'
  }

  if (
    user.crm_profile === 'admissions_director' ||
    user.role === 'Admissions Director' ||
    user.crm_capabilities?.includes('admissions.oversee')
  ) {
    return 'admissions_director'
  }

  return 'sales'
}

/**
 * Returns the navigation tree array for a given user.
 */
export function getNavigationForUser(user) {
  const roleKey = resolveUserNavigationRole(user)
  if (isDirectorWorkspaceNavigationEnabled(user)) {
    return bindDirectorWorkspaceDestinations(
      rawRoleNavigationTrees.admissions_director,
    )
  }
  // The broad workspace rollout has not released most Director views yet.
  // Keep their legacy routes until a dedicated Director workspace is ready.
  if (roleKey === 'admissions_director') {
    return rawRoleNavigationTrees.admissions_director
  }
  const trees = isRoleWorkspaceNavigationEnabled(user)
    ? roleNavigationTrees
    : rawRoleNavigationTrees
  return trees[roleKey] || trees.sales
}
