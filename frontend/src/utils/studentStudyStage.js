const CURRENT_GRADE_OPTIONS = [
  { label: '10', value: '10' },
  { label: '11', value: '11' },
  { label: '12', value: '12' },
  { label: 'Sau kỳ thi', value: 'post_exam' },
]

const STUDY_STAGE_OPTIONS = [
  { label: 'Lớp 10', value: 'grade_10' },
  { label: 'Lớp 11', value: 'grade_11' },
  { label: 'Lớp 12 - Học kỳ 1', value: 'grade_12_h1' },
  { label: 'Lớp 12 - Học kỳ 2', value: 'grade_12_h2' },
  { label: 'Sau kỳ thi', value: 'post_exam' },
]

const STUDY_STAGES_BY_GRADE = {
  10: ['grade_10'],
  11: ['grade_11'],
  12: ['grade_12_h1', 'grade_12_h2'],
  post_exam: ['post_exam'],
}

const CURRENT_GRADE_BY_STAGE = {
  grade_10: '10',
  grade_11: '11',
  grade_12_h1: '12',
  grade_12_h2: '12',
  post_exam: 'post_exam',
}

export function getCurrentGradeOptions(studyStage = '') {
  const expectedGrade = CURRENT_GRADE_BY_STAGE[studyStage]
  const options = expectedGrade
    ? CURRENT_GRADE_OPTIONS.filter((option) => option.value === expectedGrade)
    : CURRENT_GRADE_OPTIONS
  return [{ label: '', value: '' }, ...options]
}

export function getStudyStageOptions(currentGrade = '') {
  const allowedStages = STUDY_STAGES_BY_GRADE[currentGrade]
  const options = allowedStages
    ? STUDY_STAGE_OPTIONS.filter((option) => allowedStages.includes(option.value))
    : STUDY_STAGE_OPTIONS
  return [{ label: '', value: '' }, ...options]
}

export function isStudyStageCompatible(currentGrade, studyStage) {
  if (!currentGrade || !studyStage) return true
  return CURRENT_GRADE_BY_STAGE[studyStage] === currentGrade
}
