export type ProjectionKind = 'sales' | 'digital' | 'field'

export type AdmissionsProjection = {
  projection?: string
  data?: Record<string, any>
  source?: { mode?: string; status?: string }
  ai_unavailable?: boolean
}

export function projectionEndpoint(kind: ProjectionKind) {
  if (kind === 'digital') return 'crm.api.admissions_projections.get_digital_marketing_overview'
  if (kind === 'field') return 'crm.api.admissions_projections.get_field_marketing_overview'
  return 'crm.api.admissions_projections.get_admissions_overview'
}

export function buildProjectionFilters({
  fromDate,
  toDate,
  advancedFilters = {},
  team,
}: {
  fromDate?: string
  toDate?: string
  advancedFilters?: Record<string, string | undefined>
  team?: string
}) {
  return {
    from: fromDate,
    to: toDate,
    admission_year: advancedFilters.admissionTerm,
    campus: advancedFilters.campus,
    major: advancedFilters.program,
    campaign: advancedFilters.campaign,
    channel: advancedFilters.leadChannel,
    team: team && team !== 'all' ? team : undefined,
  }
}

function numberItem(name: string, title: string, value: number) {
  return {
    name,
    type: 'number_chart',
    layout: { x: 0, y: 0, w: 4, h: 3, i: name },
    data: { title, tooltip: title, value, delta: 0, deltaSuffix: '%' },
  }
}

export function projectionToDashboardItems(response: AdmissionsProjection | null | undefined) {
  const data = response?.data || {}
  const items: any[] = []
  if (typeof data.application_count === 'number') {
    items.push(numberItem('erd_application_count', 'Applications', data.application_count))
    items.push(numberItem('erd_enrolled_count', 'Enrolled', Number(data.enrolled_count || 0)))
  }
  if (Array.isArray(data.periods)) {
    items.push({
      name: 'erd_campaign_periods',
      type: 'axis_chart',
      layout: { x: 0, y: 3, w: 12, h: 8, i: 'erd_campaign_periods' },
      data: {
        data: data.periods,
        title: 'Campaign performance by period',
        subtitle: response?.source?.mode === 'legacy' ? 'Compatibility source' : 'Canonical reporting facts',
        xAxis: { title: '', key: 'period_start', type: 'category' },
        yAxis: { title: 'Count' },
        series: [{ name: 'leads', type: 'bar' }, { name: 'enrolled', type: 'bar' }],
      },
    })
  } else if (data.by_status) {
    items.push({
      name: 'erd_application_status',
      type: 'donut_chart',
      layout: { x: 0, y: 3, w: 10, h: 8, i: 'erd_application_status' },
      data: {
        data: Object.entries(data.by_status).map(([status, count]) => ({ status, count })),
        title: 'Application status',
        subtitle: 'Server-aggregated application facts',
        categoryColumn: 'status',
        valueColumn: 'count',
      },
    })
  }
  return items
}
