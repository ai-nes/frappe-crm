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
// CRM Province Mapping list once supplied.
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
  type:
    | 'interest_card'
    | 'data_table'
    | 'signal_feed'
    | 'status_panel'
    | 'conversion_funnel'
    | 'overlap_heatmap',
  data: Record<string, unknown>,
  layout: Layout,
) {
  return { name, type, data, layout }
}

function funnelRow(
  label: string,
  total: number,
  moi: number,
  trienVong: number,
  xacNhan: number,
  nhapHoc: number,
) {
  const segment = (name: string, value: number, className: string) => ({
    label: name,
    value,
    share: Number(((value / total) * 100).toFixed(1)),
    class: className,
  })

  return {
    label,
    total,
    enrolled: nhapHoc,
    ariaLabel: `${label}: ${total} Lead, ${moi} Mới, ${trienVong} Có triển vọng, ${xacNhan} Đã xác nhận, ${nhapHoc} Đã nhập học`,
    segments: [
      segment('Không chuyển đổi', total - moi, 'bg-gray-300'),
      segment('Mới', moi - trienVong, 'bg-red-600'),
      segment('Có triển vọng', trienVong - xacNhan, 'bg-red-400'),
      segment('Đã xác nhận', xacNhan - nhapHoc, 'bg-orange-500'),
      segment('Đã nhập học', nhapHoc, 'bg-green-600'),
    ],
  }
}

const interestCards = [
  { code: 'COST', title: 'Chi phí', value: 1024, ratio: '8,2% active', progress: 74, sparkline: [61, 64, 63, 69, 71, 73, 78], metrics: [{ label: '15 phút', value: '+63' }, { label: 'So với hôm qua', value: '+4,1%' }, { label: 'Đang tăng', value: 298 }, { label: 'Confidence thấp', value: 72 }], conversion: '11,8%', trend: 'Tăng', theme: 'orange', color: 'amber' },
  { code: 'PROGRAM_COMPETITOR', title: 'Ngành & trường khác', value: 864, ratio: '6,9% active', progress: 62, sparkline: [44, 47, 51, 54, 61, 66, 72], metrics: [{ label: '15 phút', value: '+91' }, { label: 'So với hôm qua', value: '+8,4%' }, { label: 'Đang tăng', value: 312 }, { label: 'Confidence thấp', value: 88 }], conversion: '9,6%', trend: 'Tăng', theme: 'red', color: 'violet' },
  { code: 'CAREER', title: 'Việc làm', value: 1386, ratio: '11,1% active', progress: 100, sparkline: [76, 78, 79, 80, 83, 84, 86], metrics: [{ label: '15 phút', value: '+28' }, { label: 'So với hôm qua', value: '+2,7%' }, { label: 'Đang tăng', value: 246 }, { label: 'Confidence thấp', value: 54 }], conversion: '18,9%', trend: 'Ổn định', theme: 'green', color: 'teal' },
  { code: 'STUDENT_LIFE', title: 'Hoạt động sinh viên', value: 742, ratio: '6,0% active', progress: 54, sparkline: [52, 51, 54, 57, 59, 61, 64], metrics: [{ label: '15 phút', value: '+17' }, { label: 'So với hôm qua', value: '+1,9%' }, { label: 'Đang tăng', value: 138 }, { label: 'Confidence thấp', value: 61 }], conversion: '13,4%', trend: 'Mới', theme: 'blue', color: 'pink' },
  { code: 'ACCOMMODATION', title: 'Chỗ ở', value: 618, ratio: '5,0% active', progress: 45, sparkline: [71, 70, 68, 66, 63, 61, 59], metrics: [{ label: '15 phút', value: '-9' }, { label: 'So với hôm qua', value: '-1,2%' }, { label: 'Đang tăng', value: 96 }, { label: 'Confidence thấp', value: 47 }], conversion: '12,1%', trend: 'Giảm', theme: 'gray', color: 'cyan' },
  { code: 'ENROLLMENT_READINESS', title: 'Sẵn sàng nhập học', value: 1580, ratio: 'Level 3–4', readinessTotal: 12450, readinessLevels: [{ level: 0, count: 5200, share: 41.8 }, { level: 1, count: 3000, share: 24.1 }, { level: 2, count: 2670, share: 21.4 }, { level: 3, count: 960, share: 7.7 }, { level: 4, count: 620, share: 5 }], operationalMetrics: [{ label: 'Đã có hồ sơ', value: 488 }, { label: 'Chưa follow-up', value: 410 }, { label: 'Quá SLA', value: 125 }], conversion: '31,7%', trend: 'Ưu tiên', theme: 'green', color: 'blue' },
  { code: 'INTERESTED', title: 'Quan tâm', value: 980, ratio: '7,9% active', progress: 68, sparkline: [50, 54, 58, 60, 63, 65, 68], metrics: [{ label: '15 phút', value: '+41' }, { label: 'So với hôm qua', value: '+3,6%' }, { label: 'Đang tăng', value: 210 }, { label: 'Confidence thấp', value: 66 }], conversion: '14,2%', trend: 'Tăng', theme: 'yellow', color: 'yellow' },
  { code: 'OTHER', title: 'Khác', value: 226, ratio: '1,8% active', progress: 18, sparkline: [22, 20, 19, 21, 20, 19, 18], metrics: [{ label: '15 phút', value: '+3' }, { label: 'So với hôm qua', value: '+0,4%' }, { label: 'Đang tăng', value: 34 }, { label: 'Confidence thấp', value: 29 }], conversion: '5,1%', trend: 'Ổn định', theme: 'gray', color: 'gray' },
]

const interestCardWidths = [3, 3, 3, 3, 4, 4, 3, 3]
let interestCardX = 0
const interestCardItems = interestCards.map((data, index) => {
  const item = customItem(
    `mock_interest_${data.code.toLowerCase()}`,
    'interest_card',
    data,
    {
      x: interestCardX,
      y: 3,
      w: interestCardWidths[index],
      h: 6,
      i: `mock_interest_${data.code.toLowerCase()}`,
    },
  )
  interestCardX += interestCardWidths[index]
  return item
})

export const aiInterestDashboardItems = [
  numberItem('mock_active_ai', 'Active Leads', 'Lead hợp lệ trong active recruitment scope', 12450, 4.6, { x: 0, y: 0, w: 4, h: 3, i: 'mock_active_ai' }),
  numberItem('mock_analyzed_15m', 'Đã phân tích ≤15 phút', 'Lead có AI profile fresh trong 15 phút', 11820, 3.8, { x: 4, y: 0, w: 3, h: 3, i: 'mock_analyzed_15m' }),
  numberItem('mock_new_signals', 'Tín hiệu mới', 'Lead có dimension NEW hoặc INCREASING', 1245, 9.2, { x: 7, y: 0, w: 3, h: 3, i: 'mock_new_signals' }),
  numberItem('mock_stale_profiles', 'AI profile đã cũ', 'Profile quá ngưỡng freshness', 630, -5.4, { x: 10, y: 0, w: 3, h: 3, i: 'mock_stale_profiles' }),
  numberItem('mock_high_confidence', 'Confidence cao', 'Profile có confidence từ 80 trở lên', 10970, 2.6, { x: 13, y: 0, w: 3, h: 3, i: 'mock_high_confidence' }),
  numberItem('mock_ready_to_enroll', 'Sẵn sàng nhập học', 'Readiness level 3–4', 1580, 6.3, { x: 16, y: 0, w: 4, h: 3, i: 'mock_ready_to_enroll' }),
  ...interestCardItems,
  axisItem(
    'mock_interest_distribution',
    'Phân bổ mối quan tâm',
    'Distinct Lead · Level ≥2 · Một Lead có thể thuộc nhiều nhóm',
    interestCards.map((item) => ({ dimension: item.title, leads: item.value })),
    'dimension',
    'leads',
    { x: 0, y: 9, w: 10, h: 8, i: 'mock_interest_distribution' },
    'bar',
    { wrapLabels: true },
  ),
  {
    name: 'mock_interest_trend',
    type: 'axis_chart' as DashboardItemType,
    layout: { x: 10, y: 9, w: 10, h: 8, i: 'mock_interest_trend' },
    data: {
      data: [
        { time: '15:45', cost: 901, competitor: 701, career: 1290, studentLife: 665, accommodation: 650, ready: 1378 },
        { time: '16:00', cost: 944, competitor: 738, career: 1311, studentLife: 681, accommodation: 642, ready: 1432 },
        { time: '16:15', cost: 972, competitor: 773, career: 1328, studentLife: 704, accommodation: 633, ready: 1486 },
        { time: '16:30', cost: 998, competitor: 821, career: 1358, studentLife: 725, accommodation: 627, ready: 1534 },
        { time: '16:45', cost: 1024, competitor: 864, career: 1386, studentLife: 742, accommodation: 618, ready: 1580 },
      ],
      title: 'Xu hướng Interest & Readiness',
      subtitle: 'Distinct Lead theo snapshot 15 phút',
      xAxis: { title: 'Thời gian', key: 'time', type: 'category' },
      yAxis: { title: 'Số Lead' },
      series: [
        { name: 'cost', type: 'line', showDataPoints: true },
        { name: 'competitor', type: 'line', showDataPoints: true },
        { name: 'career', type: 'line', showDataPoints: true },
        { name: 'studentLife', type: 'line', showDataPoints: true },
        { name: 'accommodation', type: 'line', showDataPoints: true },
        { name: 'ready', type: 'line', showDataPoints: true },
      ],
    },
  },
  customItem('mock_interest_funnel', 'conversion_funnel', {
    title: 'Interest × Funnel',
    subtitle: 'Tỷ trọng chuyển đổi và điểm rơi theo từng mối quan tâm',
    legend: [
      { label: 'Không chuyển đổi', class: 'bg-gray-300' },
      { label: 'Mới', class: 'bg-red-600' },
      { label: 'Có triển vọng', class: 'bg-red-400' },
      { label: 'Đã xác nhận', class: 'bg-orange-500' },
      { label: 'Đã nhập học', class: 'bg-green-600' },
    ],
    rows: [
      funnelRow('Chi phí', 1024, 918, 612, 448, 121),
      funnelRow('Ngành & trường khác', 864, 772, 498, 361, 83),
      funnelRow('Việc làm', 1386, 1264, 954, 722, 262),
      funnelRow('Hoạt động sinh viên', 742, 653, 442, 318, 99),
      funnelRow('Chỗ ở', 618, 552, 376, 271, 75),
    ],
  }, { x: 0, y: 17, w: 10, h: 9, i: 'mock_interest_funnel' }),
  customItem('mock_interest_overlap', 'overlap_heatmap', {
    title: 'Interest Overlap Matrix',
    subtitle: 'Số Lead đồng thời thuộc cả hai mối quan tâm · đường chéo là tổng Lead của từng nhóm',
    symmetric: true,
    max: 610,
    labels: ['Chi phí', 'Ngành/trường', 'Việc làm', 'Hoạt động', 'Chỗ ở'],
    rows: [
      { label: 'Chi phí', values: [1024, 420, 610, 180, 260] },
      { label: 'Ngành/trường', values: [420, 864, 550, 240, 190] },
      { label: 'Việc làm', values: [610, 550, 1386, 360, 220] },
      { label: 'Hoạt động', values: [180, 240, 360, 742, 150] },
      { label: 'Chỗ ở', values: [260, 190, 220, 150, 618] },
    ],
  }, { x: 10, y: 17, w: 10, h: 9, i: 'mock_interest_overlap' }),
  customItem('mock_interest_owner', 'data_table', {
    title: 'Interest × Sales Owner',
    subtitle: 'Khối lượng tín hiệu và follow-up theo nhân viên Sales',
    badge: '28 quá SLA',
    columns: [
      { key: 'sales', label: 'Sales', primary: true },
      { key: 'cost', label: 'Chi phí' },
      { key: 'program', label: 'Ngành/trường' },
      { key: 'career', label: 'Việc làm' },
      { key: 'ready', label: 'Ready' },
      { key: 'noFollowUp', label: 'Chưa follow-up' },
      { key: 'lowConfidence', label: 'Confidence thấp' },
    ],
    rows: [
      { sales: 'Nguyễn Minh Anh', cost: 142, program: 86, career: 174, ready: 64, noFollowUp: 18, lowConfidence: 9 },
      { sales: 'Trần Hải Yến', cost: 138, program: 94, career: 168, ready: 59, noFollowUp: 14, lowConfidence: 12 },
      { sales: 'Lê Hoàng Nam', cost: 126, program: 102, career: 151, ready: 53, noFollowUp: 21, lowConfidence: 8 },
      { sales: 'Phạm Thanh Hà', cost: 117, program: 78, career: 143, ready: 47, noFollowUp: 16, lowConfidence: 11 },
    ],
  }, { x: 0, y: 26, w: 11, h: 9, i: 'mock_interest_owner' }),
  customItem('mock_signal_feed', 'signal_feed', {
    title: 'Tín hiệu AI mới nhất',
    subtitle: 'Cập nhật theo quyền của Sales · gần thời gian thực',
    signals: [
      { time: '16:45', lead: 'Lê Gia Hân', message: 'Chi phí tăng Level 2 → 3 · stance NEGATIVE · đề xuất gửi chính sách học bổng.' },
      { time: '16:44', lead: 'Trần Quốc Bảo', message: 'Readiness tăng Level 2 → 3 · chưa có next follow-up.' },
      { time: '16:42', lead: 'Nguyễn Khánh Linh', message: 'Bắt đầu so sánh ngành với trường khác · confidence 91%.' },
      { time: '16:40', lead: 'Võ Minh Khang', message: 'Vấn đề chỗ ở chuyển sang RESOLVED sau cuộc gọi.' },
      { time: '16:37', lead: 'Phan Ngọc Mai', message: 'Tín hiệu mới về cơ hội việc làm · trend INCREASING.' },
    ],
  }, { x: 11, y: 26, w: 9, h: 9, i: 'mock_signal_feed' }),
  customItem('mock_actionable_leads', 'data_table', {
    title: 'Lead cần hành động',
    subtitle: 'Ready no follow-up · Cost objection · Competitor comparison · Low confidence · SLA overdue',
    badge: '410 chưa có follow-up',
    drilldown: true,
    columns: [
      { key: 'lead', label: 'Lead', primary: true },
      { key: 'owner', label: 'Sales Owner' },
      { key: 'interest', label: 'Lý do ưu tiên' },
      { key: 'readiness', label: 'Readiness' },
      { key: 'followUp', label: 'Next Follow-up' },
      { key: 'action', label: 'Recommended Action' },
    ],
    rows: [
      { lead: 'Lê Gia Hân', owner: 'Minh Anh', stage: 'Counseling', interest: 'Chi phí', level: 3, trend: 'INCREASING', stance: 'NEGATIVE', readiness: 3, confidence: '94%', latest: 'Zalo · 3 phút', analyzed: '16:45', followUp: 'Chưa có', action: 'Gửi chính sách học bổng' },
      { lead: 'Trần Quốc Bảo', owner: 'Hải Yến', stage: 'Qualified', interest: 'Sẵn sàng', level: 3, trend: 'NEW', stance: 'POSITIVE', readiness: 4, confidence: '89%', latest: 'Call · 5 phút', analyzed: '16:44', followUp: 'Chưa có', action: 'Tạo task hoàn tất hồ sơ' },
      { lead: 'Nguyễn Khánh Linh', owner: 'Hoàng Nam', stage: 'Contacted', interest: 'Ngành/trường', level: 3, trend: 'INCREASING', stance: 'UNRESOLVED', readiness: 2, confidence: '91%', latest: 'Chatwoot · 7 phút', analyzed: '16:42', followUp: '17:30 hôm nay', action: 'Gửi battlecard so sánh' },
      { lead: 'Phan Ngọc Mai', owner: 'Thanh Hà', stage: 'Counseling', interest: 'Việc làm', level: 2, trend: 'INCREASING', stance: 'POSITIVE', readiness: 3, confidence: '58%', latest: 'Email · 10 phút', analyzed: '16:37', followUp: 'Ngày mai', action: 'Sale xác nhận confidence' },
    ],
  }, { x: 0, y: 35, w: 20, h: 11, i: 'mock_actionable_leads' }),
  customItem('mock_ai_freshness', 'status_panel', {
    title: 'Độ mới dữ liệu AI',
    subtitle: 'Batch gần nhất thành công lúc 16:45',
    action: 'Refresh now',
    metrics: [
      { label: 'Data coverage', value: '94,9%' },
      { label: 'Dirty Leads waiting', value: '326' },
      { label: 'Failed jobs', value: '8' },
      { label: 'Average latency', value: '2m 12s' },
      { label: 'Batch success rate', value: '99,2%' },
    ],
  }, { x: 0, y: 46, w: 20, h: 4, i: 'mock_ai_freshness' }),
]

const salesOverviewNames = [
  'mock_active_ai',
  'mock_analyzed_15m',
  'mock_new_signals',
  'mock_stale_profiles',
  'mock_high_confidence',
  'mock_ready_to_enroll',
  'mock_interest_distribution',
  'mock_interest_trend',
  'mock_ai_freshness',
]

const salesOverviewLayout: Record<string, Partial<Layout>> = {
  mock_interest_distribution: { x: 0, y: 3, w: 10, h: 8 },
  mock_interest_trend: { x: 10, y: 3, w: 10, h: 8 },
  mock_ai_freshness: { x: 0, y: 11, w: 20, h: 4 },
}

const salesInterestLayout: Record<string, Partial<Layout>> = Object.fromEntries([
  ...interestCardItems.map((item, index) => [
    item.name,
    {
      x: (index % 4) * 5,
      y: index < 4 ? 0 : 7,
      w: 5,
      h: 7,
    },
  ]),
  ['mock_interest_funnel', { x: 0, y: 14, w: 10, h: 9 }],
  ['mock_interest_overlap', { x: 10, y: 14, w: 10, h: 9 }],
])

const salesActionLayout: Record<string, Partial<Layout>> = {
  mock_signal_feed: { x: 0, y: 0, w: 7, h: 10 },
  mock_actionable_leads: { x: 7, y: 0, w: 13, h: 10 },
  mock_interest_owner: { x: 0, y: 10, w: 20, h: 9 },
}

function dashboardSubset(
  names: string[],
  layout: Record<string, Partial<Layout>>,
) {
  const includedNames = new Set(names)
  return aiInterestDashboardItems
    .filter((item) => includedNames.has(item.name))
    .map((item) => ({
      ...item,
      layout: { ...item.layout, ...(layout[item.name] || {}) },
    }))
}

export const salesDashboardSections = {
  overview: dashboardSubset(salesOverviewNames, salesOverviewLayout),
  interests: dashboardSubset(
    [
      ...interestCardItems.map((item) => item.name),
      'mock_interest_funnel',
      'mock_interest_overlap',
    ],
    salesInterestLayout,
  ),
  actions: dashboardSubset(
    ['mock_signal_feed', 'mock_actionable_leads', 'mock_interest_owner'],
    salesActionLayout,
  ),
}

export const digitalMarketingDashboardItems = digitalMarketingItems
