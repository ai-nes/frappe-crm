import { describe, expect, it } from 'vitest'
import {
  roleNavigationTrees,
  resolveUserNavigationRole,
  getNavigationForUser,
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

    expect(labels).toContain('Cần liên hệ ngay')
    expect(labels).toContain('Hồ sơ của tôi')
    expect(labels).toContain('Hồ sơ chưa nhận')
    expect(labels).toContain('Việc của tôi')
    expect(labels).toContain('Lịch hẹn')
    expect(labels).toContain('Kết quả của tôi')
    expect(labels).toContain('Tra cứu')

    const myRecords = salesTree.find((item) => item.label === 'Hồ sơ của tôi')
    expect(myRecords.children).toBeDefined()
    const recordSubLabels = myRecords.children.map((c) => c.label)
    expect(recordSubLabels).toEqual([
      'Mới nhận',
      'Đang tư vấn',
      'Chờ nộp hồ sơ',
      'Nguội (>7 ngày)',
      'Đã chốt',
    ])
  })

  it('verifies Lead Sales navigation items structure', () => {
    const leadTree = getNavigationForUser({ crm_profile: 'lead_sales' })
    const labels = leadTree.map((item) => item.label)

    expect(labels).toContain('Bảng điều khiển nhóm')
    expect(labels).toContain('SLA nhóm')
    expect(labels).toContain('Hồ sơ nhóm')
    expect(labels).toContain('Phân công')
    expect(labels).toContain('Hiệu suất thành viên')
    expect(labels).toContain('Việc nhóm')
    expect(labels).toContain('Hồ sơ nghi trùng')
    expect(labels).toContain('Báo cáo nhóm')
    expect(labels).toContain('Tra cứu')
    expect(labels).toContain('Chính sách SLA (chỉ đọc)')
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
  })
})

