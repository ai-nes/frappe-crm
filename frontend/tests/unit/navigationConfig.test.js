import { describe, expect, it } from 'vitest'
import {
  roleNavigationTrees,
  resolveUserNavigationRole,
  getNavigationForUser,
  isDirectorWorkspaceNavigationEnabled,
  isRoleWorkspaceNavigationEnabled,
} from '../../src/utils/navigationConfig'

describe('navigationConfig', () => {
  it('defines navigation trees for all 5 canonical roles', () => {
    expect(roleNavigationTrees.sales).toBeDefined()
    expect(roleNavigationTrees.lead_sales).toBeDefined()
    expect(roleNavigationTrees.marketing).toBeDefined()
    expect(roleNavigationTrees.admissions_director).toBeDefined()
    expect(roleNavigationTrees.system_manager).toBeDefined()
  })

  it('resolves sales role for sales profile or default user', () => {
    expect(resolveUserNavigationRole({ crm_profile: 'sales', role: 'Sale' })).toBe('sales')
    expect(resolveUserNavigationRole({})).toBe('sales')
    expect(resolveUserNavigationRole(null)).toBe('sales')
  })

  it('keeps legacy destinations until the server enables workspace navigation', () => {
    const legacy = getNavigationForUser({ crm_profile: 'sales' })
    expect(legacy.find((item) => item.id === 'sales_my_records').to).toEqual({
      name: 'CRM Students',
      params: { viewType: 'list' },
    })
    expect(isRoleWorkspaceNavigationEnabled({ crm_profile: 'sales' })).toBe(false)
    const workspace = getNavigationForUser({
      crm_profile: 'sales',
      crm_feature_flags: { role_workspace_read: true },
    })
    expect(workspace.find((item) => item.id === 'sales_my_records').to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'sales-records', view: 'new' },
    })
    expect(isRoleWorkspaceNavigationEnabled({
      crm_feature_flags: { role_workspace_read: true },
    })).toBe(true)
  })

  it('routes every Director dashboard to its workspace even without rollout flags', () => {
    const workspace = getNavigationForUser({
      crm_profile: 'admissions_director',
    })
    const people = workspace.find((item) => item.id === 'mgr_teams_staff')
    const overview = workspace.find((item) => item.id === 'mgr_overview')
    expect(overview.to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'director-overview', view: 'overview' },
    })
    expect(overview.children.map((item) => item.to)).toEqual([
      { name: 'Role Workspace', params: { workspace: 'director-overview', view: 'quota-progress' } },
      { name: 'Role Workspace', params: { workspace: 'director-overview', view: 'campus' } },
      { name: 'Role Workspace', params: { workspace: 'director-overview', view: 'program' } },
    ])
    expect(workspace.find((item) => item.id === 'mgr_all_records').to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'director-records', view: 'all' },
    })
    expect(workspace.find((item) => item.id === 'mgr_funnel_forecast').to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'director-forecast', view: 'funnel' },
    })
    const sla = workspace.find((item) => item.id === 'mgr_sla_system')
    expect(sla.to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'director-sla', view: 'team' },
    })
    expect(sla.children.map((item) => item.to.params.view)).toEqual([
      'team', 'campus', 'ranking',
    ])
    expect(workspace.find((item) => item.id === 'mgr_quota_tuition').to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'admissions-reference', view: 'quota-tuition' },
    })
    expect(people.to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'director-people', view: 'team-performance' },
    })
    expect(people.children[0].to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'director-people', view: 'team-performance' },
    })
    expect(people.children[1].to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'director-people', view: 'workload' },
    })
    expect(people.children[2].to).toEqual({
      name: 'Role Workspace',
      params: { workspace: 'director-people', view: 'rebalance' },
    })
    expect(typeof workspace.find((item) => item.id === 'mgr_business_config').action)
      .toBe('function')
    expect(isDirectorWorkspaceNavigationEnabled({
      crm_profile: 'admissions_director',
    })).toBe(true)
  })

  it('resolves lead_sales role for lead_sales profile', () => {
    expect(
      resolveUserNavigationRole({ crm_profile: 'lead_sales', role: 'Lead Sales' }),
    ).toBe('lead_sales')
  })

  it('resolves marketing role for marketing profile', () => {
    expect(
      resolveUserNavigationRole({ crm_profile: 'marketing', role: 'Marketing' }),
    ).toBe('marketing')
  })

  it('resolves admissions_director role for admissions_director profile or capability', () => {
    expect(
      resolveUserNavigationRole({
        crm_profile: 'admissions_director',
        role: 'Admissions Director',
      }),
    ).toBe('admissions_director')
    expect(
      resolveUserNavigationRole({
        crm_capabilities: ['admissions.oversee'],
      }),
    ).toBe('admissions_director')
  })

  it('resolves system_manager role for System Manager or platform superuser', () => {
    expect(
      resolveUserNavigationRole({
        role: 'System Manager',
      }),
    ).toBe('system_manager')
    expect(
      resolveUserNavigationRole({
        crm_role_state: 'platform_superuser',
      }),
    ).toBe('system_manager')
    expect(
      resolveUserNavigationRole({
        crm_capabilities: ['system.configure'],
      }),
    ).toBe('system_manager')
  })

  it('verifies Sales navigation items structure according to role-navigation-menu-structure.md', () => {
    const salesTree = getNavigationForUser({ crm_profile: 'sales' })
    const labels = salesTree.map((item) => item.label)

    expect(salesTree[0].label).toBe('Dashboard')
    expect(labels).toContain('Dashboard')
    expect(labels).toContain('Cần liên hệ ngay')
    expect(labels).toContain('Lead')
    expect(labels).not.toContain('Hồ sơ chưa nhận')
    expect(labels).toContain('Việc của tôi')
    expect(labels).toContain('Lịch hẹn')
    expect(labels).toContain('Tra cứu')

    const leads = salesTree.find((item) => item.label === 'Lead')
    expect(leads.to).toEqual({
      name: 'CRM Students',
      params: { viewType: 'list' },
    })
    expect(salesTree.find((item) => item.id === 'sales_my_tasks').to).toBe('CTV Sale Tasks')
    expect(leads.children.map((item) => item.id)).toEqual([
      'sales_records_new',
      'sales_records_counseling',
      'sales_records_awaiting_docs',
      'sales_records_cold',
      'sales_records_won',
      'sales_unassigned_pool',
    ])
  })

  it('verifies Lead Sales navigation items structure', () => {
    const leadTree = getNavigationForUser({ crm_profile: 'lead_sales' })
    const labels = leadTree.map((item) => item.label)

    expect(labels).toContain('Dashboard Sale')
    expect(labels).toContain('Bảng điều khiển nhóm')
    expect(labels).toContain('SLA nhóm')
    expect(labels).toContain('Hồ sơ nhóm')
    expect(labels).toContain('Hồ sơ chưa phân công')
    expect(labels).toContain('Hiệu suất thành viên')
    expect(labels).toContain('Việc nhóm')
    expect(labels).toContain('Báo cáo nhóm')
    expect(labels).toContain('Tra cứu')
    expect(labels).toContain('Chính sách SLA (chỉ đọc)')
    expect(leadTree.filter((item) => item.label === 'Cơ chế phân bổ')).toHaveLength(1)
    expect(labels).not.toContain('Hồ sơ nghi trùng')

    expect(
      leadTree.find((item) => item.id === 'lead_sales_dashboard').to,
    ).toEqual({
      name: 'Dashboard',
      params: { section: 'overview' },
      query: { scope: 'my' },
    })

    const slaItem = leadTree.find((item) => item.id === 'lead_team_sla')
    expect(slaItem.to).toBe('CRM Student SLA Attempts')
    expect(slaItem.badgeKey).toBeUndefined()
    expect(slaItem.children).toBeDefined()
    expect(slaItem.children[0].to).toEqual({
      name: 'CRM Student SLA Attempts',
      query: { tab: 'running' },
    })
    expect(slaItem.children[1].to).toEqual({
      name: 'CRM Student SLA Attempts',
      query: { tab: 'near_breach' },
    })
    expect(slaItem.children[2].to).toEqual({
      name: 'CRM Student SLA Attempts',
      query: { tab: 'breached' },
    })
    expect(slaItem.children[2]).toMatchObject({
      badgeKey: 'teamSlaBreachedCount',
      badgeVariant: 'red',
    })
    expect(slaItem.children[3].to).toEqual({
      name: 'CRM Student SLA Attempts',
      query: { tab: 'history' },
    })

    const records = leadTree.find((item) => item.id === 'lead_team_records')
    expect(records.to).toEqual({
      name: 'CRM Students',
      query: { lead_view: 'by_stage' },
    })
    expect(records.children[0].to).toEqual({
      name: 'CRM Students',
      params: { viewType: 'list' },
      query: { lead_view: 'by_stage' },
    })
    expect(records.children[1].to).toEqual({
      name: 'CRM Students',
      params: { viewType: 'group_by' },
      query: { lead_view: 'by_agent' },
    })
    expect(records.children[2].to).toEqual({
      name: 'CRM Students',
      query: { owner: 'unassigned', lead_view: 'unassigned' },
    })

    expect(leadTree.find((item) => item.id === 'lead_assignment').to).toEqual({
      name: 'CRM Students',
      query: { owner: 'unassigned', lead_view: 'unassigned' },
    })
    expect(leadTree.find((item) => item.id === 'lead_assignment')).toMatchObject({
      label: 'Hồ sơ chưa phân công',
    })
    expect(leadTree.find((item) => item.id === 'lead_assignment').badgeKey).toBeUndefined()

    expect(records.children.map((item) => item.id)).not.toContain(
      'lead_records_cold',
    )
    expect(records.children.map((item) => item.label)).not.toContain(
      'Nguội / Bỏ rơi',
    )
    expect(leadTree.map((item) => item.id)).not.toContain('lead_duplicates')

    expect(leadTree.find((item) => item.id === 'lead_team_dashboard').to).toBe(
      'Lead Sales Dashboard',
    )
    expect(
      leadTree.find((item) => item.id === 'lead_member_performance').to,
    ).toBe('Lead Sales Performance')
    expect(leadTree.find((item) => item.id === 'lead_team_tasks').to).toBe(
      'Lead Sales Tasks',
    )
    expect(leadTree.find((item) => item.id === 'lead_team_reports').to).toBe(
      'Lead Sales Reports',
    )
    expect(
      leadTree.find((item) => item.id === 'lead_sla_policy_readonly').to,
    ).toBe('Lead Sales SLA Policies')
  })

  it('verifies Marketing navigation items structure', () => {
    const mktTree = getNavigationForUser({ crm_profile: 'marketing' })
    const labels = mktTree.map((item) => item.label)

    expect(labels).toContain('Tổng quan marketing')
    expect(labels).toContain('Chiến dịch')
    expect(labels).toContain('Chi phí')
    expect(labels).toContain('Sự kiện tuyển sinh')
    expect(labels).toContain('Nguồn & Attribution')
    expect(labels).toContain('Phễu chuyển đổi')
    expect(labels).toContain('Danh sách gửi (theo consent)')
    expect(labels).toContain('Tra cứu')
  })

  it('verifies Manager (Admissions Director) navigation items structure', () => {
    const mgrTree = getNavigationForUser({ crm_profile: 'admissions_director' })
    const labels = mgrTree.map((item) => item.label)

    expect(labels).toContain('Tổng quan tuyển sinh')
    expect(labels).toContain('Phễu & Dự báo')
    expect(labels).toContain('SLA toàn hệ')
    expect(labels).toContain('Hồ sơ (toàn bộ)')
    expect(labels).toContain('Nhóm & Nhân sự')
    expect(labels).toContain('Marketing ROI')
    expect(labels).toContain('Chờ duyệt')
    expect(labels).toContain('Chỉ tiêu & Học phí')
    expect(labels).toContain('Cấu hình nghiệp vụ')
    expect(labels).toContain('Báo cáo (Metabase)')
    const businessConfig = mgrTree.find((item) => item.id === 'mgr_business_config')
    expect(businessConfig.children.filter((item) => item.label === 'Cơ chế phân bổ')).toHaveLength(1)
    expect(businessConfig.children.map((item) => item.label)).not.toContain('Chính sách phân phối')
  })

  it('verifies Admin (System Manager) navigation items structure', () => {
    const adminTree = getNavigationForUser({ role: 'System Manager' })
    const labels = adminTree.map((item) => item.label)

    expect(labels).toContain('Người dùng & Phân quyền')
    expect(labels).toContain('Cơ cấu tổ chức')
    expect(labels).toContain('Tích hợp')
    expect(labels).toContain('API Key')
    expect(labels).toContain('Mô hình dữ liệu')
    expect(labels).toContain('Nhật ký hệ thống')
    expect(labels).toContain('Sao lưu')
    expect(labels).toContain('Break Glass (quyền tạm)')
    expect(labels).toContain('Nhật ký truy cập')
    const orgStructure = adminTree.find((item) => item.id === 'adm_org_structure')
    expect(orgStructure.children.filter((item) => item.label === 'Cơ chế phân bổ')).toHaveLength(1)
  })
})
