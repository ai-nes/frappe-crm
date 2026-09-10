import { describe, expect, it } from 'vitest'
import {
  getCurrentGradeOptions,
  getStudyStageOptions,
  isStudyStageCompatible,
} from '../../src/utils/studentStudyStage'

describe('student study-stage UI helpers', () => {
  it('limits study-stage choices to the selected current grade', () => {
    expect(getStudyStageOptions('12')).toEqual([
      { label: '', value: '' },
      { label: 'Lớp 12 - Học kỳ 1', value: 'grade_12_h1' },
      { label: 'Lớp 12 - Học kỳ 2', value: 'grade_12_h2' },
    ])
    expect(getStudyStageOptions('post_exam')).toEqual([
      { label: '', value: '' },
      { label: 'Sau kỳ thi', value: 'post_exam' },
    ])
  })

  it('limits current-grade choices to the selected study stage', () => {
    expect(getCurrentGradeOptions('grade_12_h2')).toEqual([
      { label: '', value: '' },
      { label: '12', value: '12' },
    ])
    expect(getCurrentGradeOptions()).toHaveLength(5)
  })

  it('allows either field to remain blank but rejects incompatible values', () => {
    expect(isStudyStageCompatible('', 'grade_12_h2')).toBe(true)
    expect(isStudyStageCompatible('post_exam', '')).toBe(true)
    expect(isStudyStageCompatible('12', 'grade_12_h2')).toBe(true)
    expect(isStudyStageCompatible('post_exam', 'grade_12_h2')).toBe(false)
  })
})
