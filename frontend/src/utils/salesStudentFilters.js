const SALES_STUDENT_VIEWS = Object.freeze({
  new: Object.freeze({ enrollment_status: 'Mới' }),
  counseling: Object.freeze({
    enrollment_status: ['in', ['Có triển vọng', 'Đang suy nghĩ', 'Đang tư vấn']],
  }),
  awaiting_docs: Object.freeze({ enrollment_status: ['like', '%hồ sơ%'] }),
  cold: Object.freeze({
    enrollment_status: ['in', ['Không quan tâm', 'Không triển vọng', 'Nguội']],
  }),
  won: Object.freeze({ lifecycle_stage: 'Enrolled' }),
  unassigned: Object.freeze({ owner_staff: ['is', 'not set'] }),
})

export function getSalesStudentFilters(view) {
  return { ...(SALES_STUDENT_VIEWS[view] || {}) }
}
