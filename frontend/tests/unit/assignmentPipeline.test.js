import { describe, expect, it, vi } from 'vitest'

const { call } = vi.hoisted(() => ({ call: vi.fn() }))
vi.mock('frappe-ui', () => ({ call }))

import {
  assignmentPipelineMethods,
  cleanAssignmentPipelineParams,
  getAssignmentPipelineSnapshot,
  runAssignmentPipeline,
  workflowProgress,
  workflowStepStatusClass,
} from '@/data/assignmentPipeline'

describe('assignment pipeline data contract', () => {
  it('keeps only meaningful API params', () => {
    expect(cleanAssignmentPipelineParams({ limit: 50, timezone: '', admissionYear: null })).toEqual({ limit: 50 })
  })

  it('uses the assignment snapshot and run endpoints', async () => {
    call.mockResolvedValueOnce({ workflow: { steps: [] } }).mockResolvedValueOnce({ run: { assigned: 3 } })

    await getAssignmentPipelineSnapshot({ admissionYear: '2026' })
    await runAssignmentPipeline({ limit: 3 })

    expect(call).toHaveBeenNthCalledWith(1, assignmentPipelineMethods.snapshot, {
      page: 1,
      pageSize: 1,
      admissionYear: '2026',
    })
    expect(call).toHaveBeenNthCalledWith(2, assignmentPipelineMethods.run, { limit: 3 })
  })

  it('calculates completed workflow steps from server status', () => {
    expect(workflowProgress({ steps: [{ status: 'success' }, { status: 'warning' }, { status: 'success' }] })).toEqual({
      completed: 2,
      total: 3,
    })
    expect(workflowStepStatusClass('warning')).toBe('is-warning')
    expect(workflowStepStatusClass('unknown')).toBe('is-neutral')
  })
})
