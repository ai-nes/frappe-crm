type DashboardItemType =
  | 'number_chart'
  | 'axis_chart'
  | 'donut_chart'

type Layout = {
  x: number
  y: number
  w: number
  h: number
  i: string
}

function numberItem(
  name: string,
  title: string,
  tooltip: string,
  value: number,
  delta: number,
  layout: Layout,
) {
  return {
    name,
    type: 'number_chart' as DashboardItemType,
    layout,
    data: { title, tooltip, value, delta, deltaSuffix: '%' },
  }
}

function axisItem(
  name: string,
  title: string,
  subtitle: string,
  data: Record<string, string | number>[],
  category: string,
  value: string,
  layout: Layout,
  type: 'bar' | 'line' = 'bar',
  options: { wrapLabels?: boolean } = {},
) {
  return {
    name,
    type: 'axis_chart' as DashboardItemType,
    layout,
    data: {
      data,
      title,
      subtitle,
      xAxis: { title: '', key: category, type: 'category', wrapLabels: options.wrapLabels },
      yAxis: { title: 'Số lượng' },
      series: [{ name: value, type, showDataPoints: type === 'line' }],
    },
  }
}

function donutItem(
  name: string,
  title: string,
  subtitle: string,
  data: Record<string, string | number>[],
  category: string,
  layout: Layout,
) {
  return {
    name,
    type: 'donut_chart' as DashboardItemType,
    layout,
    data: {
      data,
      title,
      subtitle,
      categoryColumn: category,
      valueColumn: 'count',
    },
  }
}

const salesItems = [
  numberItem('mock_new_leads', 'Lead mới', 'Lead tạo trong kỳ', 1248, 12.4, { x: 0, y: 0, w: 4, h: 3, i: 'mock_new_leads' }),
  numberItem('mock_active_leads', 'Lead đang hoạt động', 'Lead trong active pipeline', 842, 6.8, { x: 4, y: 0, w: 4, h: 3, i: 'mock_active_leads' }),
  numberItem('mock_sla_rate', 'Đúng SLA liên hệ (%)', 'Lead được liên hệ đúng SLA', 91.6, 3.2, { x: 8, y: 0, w: 4, h: 3, i: 'mock_sla_rate' }),
  numberItem('mock_overdue_leads', 'Lead quá hạn', 'Lead cần xử lý ngay', 37, -14, { x: 12, y: 0, w: 4, h: 3, i: 'mock_overdue_leads' }),
  numberItem('mock_enrolled', 'Đã nhập học', 'Lead đã chuyển đổi trong kỳ', 126, 18.9, { x: 16, y: 0, w: 4, h: 3, i: 'mock_enrolled' }),
  axisItem(
    'mock_admission_funnel',
    'Funnel tuyển sinh',
    'Số Lead đã đi vào từng giai đoạn',
    [
      { stage: 'Lead mới', count: 1248 },
      { stage: 'Đã liên hệ', count: 1017 },
      { stage: 'Đủ điều kiện', count: 614 },
      { stage: 'Đang tư vấn', count: 438 },
      { stage: 'Đã nộp hồ sơ', count: 244 },
      { stage: 'Đã nhập học', count: 126 },
    ],
    'stage',
    'count',
    { x: 0, y: 3, w: 10, h: 8, i: 'mock_admission_funnel' },
  ),
  axisItem(
    'mock_weekly_leads',
    'Lead mới theo tuần',
    'Xu hướng 12 tuần gần nhất',
    [44, 51, 48, 67, 72, 64, 86, 79, 93, 88, 105, 111].map((count, index) => ({ week: `T${index + 1}`, count })),
    'week',
    'count',
    { x: 10, y: 3, w: 10, h: 8, i: 'mock_weekly_leads' },
    'line',
  ),
  donutItem(
    'mock_readiness',
    'Mức sẵn sàng nhập học',
    'Phân bổ readiness hiện tại',
    [
      { readiness: 'Sẵn sàng cao', count: 238 },
      { readiness: 'Đang cân nhắc', count: 416 },
      { readiness: 'Cần nuôi dưỡng', count: 372 },
      { readiness: 'Chưa xác định', count: 222 },
    ],
    'readiness',
    { x: 0, y: 11, w: 8, h: 8, i: 'mock_readiness' },
  ),
  axisItem(
    'mock_sales_performance',
    'Hiệu suất tư vấn',
    'Enrollment theo nhân viên Sales',
    [
      { sales: 'Minh Anh', enrolled: 24 },
      { sales: 'Hải Yến', enrolled: 21 },
      { sales: 'Hoàng Nam', enrolled: 19 },
      { sales: 'Thanh Hà', enrolled: 17 },
      { sales: 'Gia Bảo', enrolled: 15 },
    ],
    'sales',
    'enrolled',
    { x: 8, y: 11, w: 12, h: 8, i: 'mock_sales_performance' },
  ),
]

const digitalMarketingItems = [
  numberItem('mock_marketing_leads', 'Digital Marketing Lead', 'Lead đến từ các nguồn Digital', 1086, 15.2, { x: 0, y: 0, w: 4, h: 3, i: 'mock_marketing_leads' }),
  numberItem('mock_valid_rate', 'Valid Lead Rate (%)', 'Tỷ lệ Lead hợp lệ', 94.8, 2.1, { x: 4, y: 0, w: 4, h: 3, i: 'mock_valid_rate' }),
  numberItem('mock_qualified_rate', 'Qualified Rate (%)', 'Tỷ lệ Lead đủ điều kiện', 48.9, 5.4, { x: 8, y: 0, w: 4, h: 3, i: 'mock_qualified_rate' }),
  numberItem('mock_cpl', 'CPL (nghìn đồng)', 'Chi phí trung bình trên mỗi Lead', 394, -9.7, { x: 12, y: 0, w: 4, h: 3, i: 'mock_cpl' }),
  numberItem('mock_cost_enrollment', 'Chi phí / Enrollment (triệu)', 'Chi phí trung bình trên mỗi enrollment', 3.7, -11.2, { x: 16, y: 0, w: 4, h: 3, i: 'mock_cost_enrollment' }),
  donutItem(
    'mock_leads_by_platform',
    'Lead theo Platform',
    'Phân bổ 1.086 Lead theo nhóm nguồn (Lead Source)',
    [
      { platform: 'Facebook', count: 328 },
      { platform: 'Google', count: 219 },
      { platform: 'Zalo', count: 168 },
      { platform: 'Website', count: 159 },
      { platform: 'TikTok', count: 134 },
      { platform: 'Referral', count: 78 },
    ],
    'platform',
    { x: 0, y: 3, w: 10, h: 8, i: 'mock_leads_by_platform' },
  ),
  {
    name: 'mock_form_landing_split',
    type: 'axis_chart' as DashboardItemType,
    layout: { x: 10, y: 3, w: 10, h: 8, i: 'mock_form_landing_split' },
    data: {
      data: [
        { platform: 'Facebook', Form: 186, 'Landing Page': 142 },
        { platform: 'Google', Form: 121, 'Landing Page': 98 },
      ],
      title: 'Chi tiết Form vs Landing Page',
      subtitle: 'Facebook & Google là 2 nguồn có tách sub-channel',
      xAxis: { title: '', key: 'platform', type: 'category' },
      yAxis: { title: 'Số lượng' },
      series: [
        { name: 'Form', type: 'bar' },
        { name: 'Landing Page', type: 'bar' },
      ],
    },
  },
  customItem('mock_source_platform_matrix', 'overlap_heatmap', {
    title: 'Ma trận Nguồn × Platform',
    subtitle: 'Số Lead theo từng Lead Source và sub-channel (Platform) tương ứng',
    max: 186,
    labels: ['Form', 'Landing Page', 'Trực tiếp'],
    rows: [
      { label: 'Facebook', values: [186, 142, null] },
      { label: 'Google', values: [121, 98, null] },
      { label: 'Zalo', values: [null, null, 168] },
      { label: 'TikTok', values: [null, null, 134] },
      { label: 'Referral', values: [null, null, 78] },
      { label: 'Website', values: [null, null, 159] },
    ],
  }, { x: 0, y: 11, w: 10, h: 9, i: 'mock_source_platform_matrix' }),
  axisItem(
    'mock_source_quality',
    'Qualified Lead theo nguồn',
    'Chất lượng Lead theo Lead Source',
    [
      { source: 'Facebook', qualified: 152 },
      { source: 'Google', qualified: 98 },
      { source: 'Zalo', qualified: 74 },
      { source: 'TikTok', qualified: 61 },
      { source: 'Website', qualified: 71 },
      { source: 'Referral', qualified: 34 },
    ],
    'source',
    'qualified',
    { x: 10, y: 11, w: 10, h: 9, i: 'mock_source_quality' },
  ),
  {
    name: 'mock_campaign_contact',
    type: 'axis_chart' as DashboardItemType,
    layout: { x: 0, y: 20, w: 12, h: 8, i: 'mock_campaign_contact' },
    data: {
      data: [
        { campaign: 'Open Day 2026', 'Đã chuyển đổi': 28, 'Có triển vọng': 64, 'Sai số': 12, 'Sai đối tượng': 9, 'Không liên lạc được': 18 },
        { campaign: 'GenZ chọn ngành đúng', 'Đã chuyển đổi': 31, 'Có triển vọng': 58, 'Sai số': 15, 'Sai đối tượng': 21, 'Không liên lạc được': 14 },
        { campaign: 'FPTU Scholarship', 'Đã chuyển đổi': 27, 'Có triển vọng': 49, 'Sai số': 8, 'Sai đối tượng': 6, 'Không liên lạc được': 11 },
        { campaign: 'Campus Tour', 'Đã chuyển đổi': 12, 'Có triển vọng': 33, 'Sai số': 19, 'Sai đối tượng': 24, 'Không liên lạc được': 22 },
      ],
      title: 'Contact theo chiến dịch',
      subtitle: 'Phân bổ Contact theo trạng thái Lead (Sai đối tượng ~ quan tâm ngành khác) cho từng chiến dịch',
      xAxis: { title: '', key: 'campaign', type: 'category' },
      yAxis: { title: 'Số lượng' },
      series: [
        { name: 'Đã chuyển đổi', type: 'bar' },
        { name: 'Có triển vọng', type: 'bar' },
        { name: 'Sai số', type: 'bar' },
        { name: 'Sai đối tượng', type: 'bar' },
        { name: 'Không liên lạc được', type: 'bar' },
      ],
    },
  },
  donutItem(
    'mock_primary_interest',
    'Mối quan tâm nổi bật',
    'Tổng hợp từ Lead Interest Event',
    [
      { interest: 'Cơ hội nghề nghiệp', count: 468 },
      { interest: 'Học phí & học bổng', count: 396 },
      { interest: 'Chương trình đào tạo', count: 348 },
      { interest: 'Môi trường quốc tế', count: 258 },
    ],
    'interest',
    { x: 12, y: 20, w: 8, h: 8, i: 'mock_primary_interest' },
  ),
]

export type OfflineTeam = 'all' | 'Team North' | 'Team Central' | 'Team South'

const offlineRegionData: Record<OfflineTeam, { region: string; onCampus: number; offCampus: number }[]> = {
  all: [
    { region: 'Miền Bắc', onCampus: 86, offCampus: 142 },
    { region: 'Miền Trung', onCampus: 54, offCampus: 98 },
    { region: 'Miền Nam', onCampus: 71, offCampus: 168 },
  ],
  'Team North': [{ region: 'Miền Bắc', onCampus: 86, offCampus: 142 }],
  'Team Central': [{ region: 'Miền Trung', onCampus: 54, offCampus: 98 }],
  'Team South': [{ region: 'Miền Nam', onCampus: 71, offCampus: 168 }],
}

const offlineInterestData: Record<OfflineTeam, { interest: string; count: number }[]> = {
  all: [
    { interest: 'Học phí & học bổng', count: 218 },
    { interest: 'Ngành đào tạo', count: 186 },
    { interest: 'Cơ hội việc làm', count: 164 },
    { interest: 'Môi trường sinh viên', count: 122 },
    { interest: 'Khác', count: 58 },
  ],
  'Team North': [
    { interest: 'Học phí & học bổng', count: 92 },
    { interest: 'Ngành đào tạo', count: 74 },
    { interest: 'Cơ hội việc làm', count: 61 },
    { interest: 'Môi trường sinh viên', count: 48 },
    { interest: 'Khác', count: 21 },
  ],
  'Team Central': [
    { interest: 'Học phí & học bổng', count: 58 },
    { interest: 'Ngành đào tạo', count: 52 },
    { interest: 'Cơ hội việc làm', count: 45 },
    { interest: 'Môi trường sinh viên', count: 31 },
    { interest: 'Khác', count: 16 },
  ],
  'Team South': [
    { interest: 'Học phí & học bổng', count: 68 },
    { interest: 'Ngành đào tạo', count: 60 },
    { interest: 'Cơ hội việc làm', count: 58 },
    { interest: 'Môi trường sinh viên', count: 43 },
    { interest: 'Khác', count: 21 },
  ],
}

// Placeholder old→new province merger grouping — replace with the authoritative
// CRM Province.previous_names list once supplied.
const offlineProvinceGroups: Record<
  OfflineTeam,
  { newProvince: string; oldProvinces: { name: string; count: number }[] }[]
> = {
  all: [
    { newProvince: 'Bắc Ninh', oldProvinces: [{ name: 'Bắc Ninh', count: 64 }, { name: 'Bắc Giang', count: 58 }] },
    { newProvince: 'Ninh Bình', oldProvinces: [{ name: 'Ninh Bình', count: 42 }, { name: 'Hà Nam', count: 38 }] },
    { newProvince: 'Quảng Ngãi', oldProvinces: [{ name: 'Quảng Ngãi', count: 39 }, { name: 'Kon Tum', count: 27 }] },
    { newProvince: 'Gia Lai', oldProvinces: [{ name: 'Bình Định', count: 46 }, { name: 'Gia Lai', count: 33 }] },
    { newProvince: 'TP. Hồ Chí Minh', oldProvinces: [{ name: 'TP. Hồ Chí Minh', count: 88 }, { name: 'Bà Rịa - Vũng Tàu', count: 41 }] },
    { newProvince: 'An Giang', oldProvinces: [{ name: 'An Giang', count: 52 }, { name: 'Kiên Giang', count: 47 }] },
  ],
  'Team North': [
    { newProvince: 'Bắc Ninh', oldProvinces: [{ name: 'Bắc Ninh', count: 64 }, { name: 'Bắc Giang', count: 58 }] },
    { newProvince: 'Ninh Bình', oldProvinces: [{ name: 'Ninh Bình', count: 42 }, { name: 'Hà Nam', count: 38 }] },
  ],
  'Team Central': [
    { newProvince: 'Quảng Ngãi', oldProvinces: [{ name: 'Quảng Ngãi', count: 39 }, { name: 'Kon Tum', count: 27 }] },
    { newProvince: 'Gia Lai', oldProvinces: [{ name: 'Bình Định', count: 46 }, { name: 'Gia Lai', count: 33 }] },
  ],
  'Team South': [
    { newProvince: 'TP. Hồ Chí Minh', oldProvinces: [{ name: 'TP. Hồ Chí Minh', count: 88 }, { name: 'Bà Rịa - Vũng Tàu', count: 41 }] },
    { newProvince: 'An Giang', oldProvinces: [{ name: 'An Giang', count: 52 }, { name: 'Kiên Giang', count: 47 }] },
  ],
}

export function offlineMarketingDashboardItems(team: OfflineTeam) {
  const isFiltered = team !== 'all'

  const eventChart = {
    name: 'mock_offline_region',
    type: 'axis_chart' as DashboardItemType,
    layout: { x: 0, y: 0, w: 10, h: 8, i: 'mock_offline_region' },
    data: {
      data: offlineRegionData[team].map((row) => ({
        region: row.region,
        'On-campus': row.onCampus,
        'Off-campus': row.offCampus,
      })),
      title: 'Lead theo Khu vực & Hình thức sự kiện',
      subtitle: isFiltered ? `Team đang chọn: ${team}` : 'Tổng quan tất cả team · On-campus vs Off-campus',
      xAxis: { title: '', key: 'region', type: 'category' },
      yAxis: { title: 'Số lượng' },
      series: [
        { name: 'On-campus', type: 'bar' },
        { name: 'Off-campus', type: 'bar' },
      ],
    },
  }

  const interestChart = donutItem(
    'mock_offline_interest',
    'Mối quan tâm từ sự kiện',
    isFiltered ? `Team đang chọn: ${team}` : 'Tổng quan tất cả team',
    offlineInterestData[team],
    'interest',
    { x: 10, y: 0, w: 10, h: 8, i: 'mock_offline_interest' },
  )

  const leadQualityChart = {
    name: 'mock_offline_lead_quality',
    type: 'axis_chart' as DashboardItemType,
    layout: { x: 0, y: 8, w: 10, h: 8, i: 'mock_offline_lead_quality' },
    data: {
      data: [
        { category: 'Hot', count: 96 },
        { category: 'Warm', count: 184 },
        { category: 'Cool', count: 142 },
        { category: 'Sai số', count: 58 },
        { category: 'KLLĐ', count: 74 },
        { category: 'Không quan tâm', count: 91 },
      ],
      title: 'Lead thu được theo phân loại',
      subtitle: 'Toàn bộ Lead thu được từ sự kiện On-campus & Off-campus',
      xAxis: { title: '', key: 'category', type: 'category' },
      yAxis: { title: 'Số lượng' },
      series: [{ name: 'count', type: 'bar' }],
      echartOptions: {
        xAxis: {
          axisLabel: {
            interval: 0,
            fontSize: 11,
          },
        },
      },
    },
  }

  const provinceRows = isFiltered
    ? offlineProvinceGroups[team].flatMap((group) =>
        group.oldProvinces.map((province) => ({ province: province.name, verified: province.count })),
      )
    : offlineProvinceGroups.all.map((group) => ({
        province: group.newProvince,
        province_detail: group.oldProvinces.map((p) => p.name).join(', '),
        verified: group.oldProvinces.reduce((acc, p) => acc + p.count, 0),
      }))

  const provinceChart = {
    name: 'mock_offline_province',
    type: 'axis_chart' as DashboardItemType,
    layout: { x: 10, y: 8, w: 10, h: 8, i: 'mock_offline_province' },
    data: {
      data: provinceRows,
      title: 'Verified Lead theo địa bàn',
      subtitle: isFiltered
        ? `Team đang chọn: ${team} · chi tiết từng tỉnh`
        : 'Tỉnh mới · gộp từ nhiều tỉnh cũ',
      xAxis: { title: '', key: 'province', type: 'category', wrapLabels: true },
      yAxis: { title: 'Verified Lead' },
      series: [{ name: 'verified', type: 'bar' }],
      echartOptions: {
        xAxis: {
          axisLabel: {
            interval: 0,
            rotate: 0,
            fontSize: 11,
          },
        },
      },
    },
  }

  return [eventChart, interestChart, leadQualityChart, provinceChart]
}

const qualityItems = [
  numberItem('mock_completeness', 'Data Completeness (%)', 'Mức độ đầy đủ của các field bắt buộc', 96.2, 1.5, { x: 0, y: 0, w: 4, h: 3, i: 'mock_completeness' }),
  numberItem('mock_valid_source', 'Source hợp lệ (%)', 'Mục tiêu tối thiểu 95%', 97.4, 1.2, { x: 4, y: 0, w: 4, h: 3, i: 'mock_valid_source' }),
  numberItem('mock_sales_owner', 'Có Sales owner (%)', 'Mục tiêu tối thiểu 98%', 98.6, 0.8, { x: 8, y: 0, w: 4, h: 3, i: 'mock_sales_owner' }),
  numberItem('mock_stage_history', 'Stage History hợp lệ (%)', 'Mục tiêu tối thiểu 98%', 96.8, -1.2, { x: 12, y: 0, w: 4, h: 3, i: 'mock_stage_history' }),
  numberItem('mock_open_issues', 'Lỗi dữ liệu đang mở', 'Tổng bản ghi cần xử lý', 106, -8.6, { x: 16, y: 0, w: 4, h: 3, i: 'mock_open_issues' }),
  axisItem(
    'mock_quality_trend',
    'Xu hướng Data Completeness',
    'Điểm chất lượng dữ liệu trong 6 tuần',
    [91.2, 92.8, 93.1, 94.7, 95.4, 96.2].map((score, index) => ({ week: `T${index + 1}`, score })),
    'week',
    'score',
    { x: 0, y: 3, w: 10, h: 8, i: 'mock_quality_trend' },
    'line',
  ),
  axisItem(
    'mock_quality_issues',
    'Lỗi dữ liệu theo quy tắc',
    'Các nhóm lỗi cần ưu tiên xử lý',
    [
      { rule: 'Lead quá SLA', count: 37 },
      { rule: 'Sai mapping nguồn', count: 32 },
      { rule: 'Lead trùng', count: 23 },
      { rule: 'Thiếu liên hệ', count: 14 },
      { rule: 'Stage không hợp lệ', count: 0 },
    ],
    'rule',
    'count',
    { x: 10, y: 3, w: 10, h: 8, i: 'mock_quality_issues' },
  ),
  donutItem(
    'mock_issue_severity',
    'Mức độ lỗi dữ liệu',
    'Phân nhóm theo mức độ ảnh hưởng',
    [
      { severity: 'Cao', count: 60 },
      { severity: 'Trung bình', count: 46 },
      { severity: 'Thấp', count: 0 },
    ],
    'severity',
    { x: 0, y: 11, w: 10, h: 8, i: 'mock_issue_severity' },
  ),
  donutItem(
    'mock_ai_readiness',
    'Điều kiện chuyển Phase AI',
    'Ba trong bốn tiêu chí đã đạt ngưỡng',
    [
      { status: 'Đã đạt', count: 3 },
      { status: 'Chưa đạt', count: 1 },
    ],
    'status',
    { x: 10, y: 11, w: 10, h: 8, i: 'mock_ai_readiness' },
  ),
]

function customItem(
  name: string,
  type: 'overlap_heatmap',
  data: Record<string, unknown>,
  layout: Layout,
) {
  return { name, type, data, layout }
}

export const salesDashboardItems = salesItems
export const digitalMarketingDashboardItems = digitalMarketingItems
