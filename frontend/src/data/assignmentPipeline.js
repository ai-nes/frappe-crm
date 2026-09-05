import { call } from 'frappe-ui'

export const assignmentPipelineMethods = Object.freeze({
  snapshot: 'crm.api.lead_sale.get_student_assignment_workspace',
  run: 'crm.api.lead_sale.run_student_assignment_pipeline',
})

export async function getAssignmentPipelineSnapshot(params = {}) {
  return call(assignmentPipelineMethods.snapshot, {
    page: 1,
    pageSize: 1,
    ...cleanAssignmentPipelineParams(params),
  })
}

export async function runAssignmentPipeline(params = {}) {
  return call(assignmentPipelineMethods.run, cleanAssignmentPipelineParams(params))
}

export function cleanAssignmentPipelineParams(params = {}) {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )
}

export function workflowProgress(workflow) {
  const steps = Array.isArray(workflow?.steps) ? workflow.steps : []
  return {
    completed: steps.filter((step) => step.status === 'success').length,
    total: steps.length,
  }
}

export function workflowStepStatusClass(status) {
  return {
    success: 'is-success',
    warning: 'is-warning',
    error: 'is-error',
  }[status] || 'is-neutral'
}
