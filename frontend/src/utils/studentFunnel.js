const TERMINAL_STAGES = ['Enrolled', 'Lost']

export function getStudentFunnelFilters(stage) {
  if (stage === 'enrolled') {
    return { lifecycle_stage: 'Enrolled' }
  }

  return { lifecycle_stage: ['not in', TERMINAL_STAGES] }
}
