import { describe, expect, it } from 'vitest'
import source from '../../src/components/Student360Dashboard.vue?raw'

describe('Student 360 dashboard boundary', () => {
  it('uses the request-driven reader and keeps the surface awareness-only', () => {
    expect(source).toContain('crm.api.analysis_run_read.get_student_360')
    expect(source).toContain("load({ request: true })")
    expect(source).toContain("load({ request: true, refresh: true })")
    expect(source).toContain('advisory_signals')
    expect(source).toContain('opportunity_signals')
    expect(source).toContain('score_overview')
    expect(source).toContain('interaction_journal')
    expect(source).not.toContain('recommended_actions')
    expect(source).not.toContain('stream_chat')
    expect(source).not.toContain('next_best_action')
    expect(source).not.toContain('Reasoning summary')
  })
})
