export const SALES_TASKS_METHOD = 'crm.api.task.list_sales_tasks'
export const SALES_TASKS_PAGE_LENGTH = 20

function compactParams(params) {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )
}

export function buildSalesTasksParams(filters = {}, start = 0) {
  return compactParams({
    search: filters.search?.trim(),
    date_filter: filters.dateFilter || 'all',
    status: filters.status,
    priority: filters.priority,
    task_type: filters.taskType,
    start,
    page_length: SALES_TASKS_PAGE_LENGTH,
    sort_by: filters.sortBy || 'due_date_asc',
  })
}

export function normalizeSalesTasksResponse(payload = {}) {
  const tasks = Array.isArray(payload.tasks) ? payload.tasks : []
  return {
    tasks,
    total: Number(payload.total_count ?? payload.total ?? tasks.length),
    start: Number(payload.start || 0),
    pageLength: Number(payload.page_length || SALES_TASKS_PAGE_LENGTH),
    hasMore: Boolean(payload.has_more),
  }
}
