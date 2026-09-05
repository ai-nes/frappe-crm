import { describe, expect, it } from 'vitest'
import {
  buildSalesTasksParams,
  normalizeSalesTasksResponse,
  SALES_TASKS_METHOD,
} from '@/data/salesTasks'

describe('sales task workbench API contract', () => {
  it('builds the aggregate endpoint params without empty filters', () => {
    expect(SALES_TASKS_METHOD).toBe('crm.api.task.list_sales_tasks')
    expect(buildSalesTasksParams({ dateFilter: 'today', status: '', taskType: '' })).toEqual({
      date_filter: 'today',
      start: 0,
      page_length: 20,
      sort_by: 'due_date_asc',
    })
  })

  it('normalizes task pages and keeps server pagination metadata', () => {
    expect(normalizeSalesTasksResponse({
      tasks: [{ task_id: 'Task:1' }],
      total_count: 3,
      start: 1,
      page_length: 2,
      has_more: 1,
    })).toEqual({
      tasks: [{ task_id: 'Task:1' }],
      total: 3,
      start: 1,
      pageLength: 2,
      hasMore: true,
    })
  })
})
