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
) {
  return {
    name,
    type: 'axis_chart' as DashboardItemType,
    layout,
    data: {
      data,
      title,
      subtitle,
      xAxis: { title: '', key: category, type: 'category' },
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

const marketingItems = [
  numberItem('mock_marketing_leads', 'Marketing Lead', 'Lead đến từ các kênh Marketing', 1086, 15.2, { x: 0, y: 0, w: 4, h: 3, i: 'mock_marketing_leads' }),
  numberItem('mock_valid_rate', 'Valid Lead Rate (%)', 'Tỷ lệ Lead hợp lệ', 94.8, 2.1, { x: 4, y: 0, w: 4, h: 3, i: 'mock_valid_rate' }),
  numberItem('mock_qualified_rate', 'Qualified Rate (%)', 'Tỷ lệ Lead đủ điều kiện', 48.9, 5.4, { x: 8, y: 0, w: 4, h: 3, i: 'mock_qualified_rate' }),
  numberItem('mock_cpl', 'CPL (nghìn đồng)', 'Chi phí trung bình trên mỗi Lead', 394, -9.7, { x: 12, y: 0, w: 4, h: 3, i: 'mock_cpl' }),
  numberItem('mock_cost_enrollment', 'Chi phí / Enrollment (triệu)', 'Chi phí trung bình trên mỗi enrollment', 3.7, -11.2, { x: 16, y: 0, w: 4, h: 3, i: 'mock_cost_enrollment' }),
  donutItem(
    'mock_leads_by_channel',
    'Lead theo kênh',
    'Phân bổ 1.086 Marketing Lead',
    [
      { channel: 'Meta Ads', count: 386 },
      { channel: 'Google Ads', count: 294 },
      { channel: 'Sự kiện THPT', count: 196 },
      { channel: 'Organic', count: 132 },
      { channel: 'Đối tác', count: 78 },
    ],
    'channel',
    { x: 0, y: 3, w: 10, h: 8, i: 'mock_leads_by_channel' },
  ),
  axisItem(
    'mock_campaign_conversion',
    'Enrollment theo chiến dịch',
    'So sánh hiệu quả chuyển đổi campaign',
    [
      { campaign: 'Open Day 2026', enrolled: 28 },
      { campaign: 'GenZ chọn ngành đúng', enrolled: 31 },
      { campaign: 'FPTU Scholarship', enrolled: 27 },
      { campaign: 'Campus Tour', enrolled: 12 },
    ],
    'campaign',
    'enrolled',
    { x: 10, y: 3, w: 10, h: 8, i: 'mock_campaign_conversion' },
  ),
  axisItem(
    'mock_source_quality',
    'Qualified Lead theo nguồn',
    'Chất lượng Lead theo nguồn chính',
    [
      { source: 'Facebook', qualified: 184 },
      { source: 'Google', qualified: 157 },
      { source: 'Sự kiện', qualified: 104 },
      { source: 'Website', qualified: 58 },
      { source: 'Đối tác', qualified: 28 },
    ],
    'source',
    'qualified',
    { x: 0, y: 11, w: 10, h: 8, i: 'mock_source_quality' },
  ),
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
    { x: 10, y: 11, w: 10, h: 8, i: 'mock_primary_interest' },
  ),
]

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
  contacted: number,
  qualified: number,
  counseling: number,
  application: number,
  enrolled: number,
) {
  const segment = (name: string, value: number, className: string) => ({
    label: name,
    value,
    share: Number(((value / contacted) * 100).toFixed(1)),
    class: className,
  })

  return {
    label,
    contacted,
    enrolled,
    ariaLabel: `${label}: ${contacted} Contacted, ${qualified} Qualified, ${counseling} Counseling, ${application} Application, ${enrolled} Enrolled`,
    segments: [
      segment('Enrolled', enrolled, 'bg-green-500'),
      segment('Dừng ở Application', application - enrolled, 'bg-blue-700'),
      segment('Dừng ở Counseling', counseling - application, 'bg-blue-500'),
      segment('Dừng ở Qualified', qualified - counseling, 'bg-blue-300'),
      segment('Dừng sau Contacted', contacted - qualified, 'bg-blue-200'),
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
]

const interestCardWidths = [3, 3, 3, 3, 4, 4]
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
      { label: 'Enrolled', class: 'bg-green-500' },
      { label: 'Dừng ở Application', class: 'bg-blue-700' },
      { label: 'Dừng ở Counseling', class: 'bg-blue-500' },
      { label: 'Dừng ở Qualified', class: 'bg-blue-300' },
      { label: 'Dừng sau Contacted', class: 'bg-blue-200' },
    ],
    rows: [
      funnelRow('Chi phí', 918, 612, 448, 201, 121),
      funnelRow('Ngành & trường khác', 772, 498, 361, 164, 83),
      funnelRow('Việc làm', 1264, 954, 722, 398, 262),
      funnelRow('Hoạt động sinh viên', 653, 442, 318, 164, 99),
      funnelRow('Chỗ ở', 552, 376, 271, 126, 75),
    ],
  }, { x: 0, y: 17, w: 10, h: 9, i: 'mock_interest_funnel' }),
  customItem('mock_interest_overlap', 'overlap_heatmap', {
    title: 'Interest Overlap Matrix',
    subtitle: 'Màu đậm hơn = nhiều Lead đồng thời thuộc hai nhóm',
    max: 610,
    labels: ['Chi phí', 'Ngành/trường', 'Việc làm', 'Hoạt động', 'Chỗ ở'],
    rows: [
      { label: 'Chi phí', values: [null, 420, 610, 180, 260] },
      { label: 'Ngành/trường', values: [420, null, 550, 240, 190] },
      { label: 'Việc làm', values: [610, 550, null, 360, 220] },
      { label: 'Hoạt động', values: [180, 240, 360, null, 150] },
      { label: 'Chỗ ở', values: [260, 190, 220, 150, null] },
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
      x: index % 3 === 0 ? 0 : index % 3 === 1 ? 7 : 14,
      y: index < 3 ? 0 : 7,
      w: index % 3 === 2 ? 6 : 7,
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

export const marketingDashboardItems = marketingItems
