import { describe, expect, it } from 'vitest'
import { ACTION_VIEW_MODEL_CONTRACT, actionWorkbenchApi, normalizeActionViewModel } from '../../src/utils/actionWorkbench'

const raw = (overrides = {}) => ({
  contract_version: ACTION_VIEW_MODEL_CONTRACT, action_id: 'ACT-1', action_revision: 3,
  freshness: { label: 'fresh', as_of: '2026-09-01', age_seconds: 10, context_current: true },
  what: { title: 'What', body: 'Call student', evidence: ['Recent inquiry'], gaps: ['No answer'] },
  why: { title: 'Why', body: 'Follow up' }, how: { title: 'How', body: 'Use approved flow' },
  goal: { title: 'Goal', body: 'Confirm next step' }, action: { title: 'Action', body: 'Review' },
  allowed_operations: [{ operation_id: 'claim', label: 'Claim', available: true }], ...overrides,
})

describe('action workbench adapter', () => {
  it('normalizes the v1 contract and keeps server operation ids', () => {
    const model = normalizeActionViewModel(raw())
    expect(model.state).toBe('available')
    expect(model.sections.what.evidence).toEqual(['Recent inquiry'])
    expect(model.allowedOperations[0].operationId).toBe('claim')
  })
  it('fails closed for unsupported or incomplete contracts', () => {
    expect(normalizeActionViewModel({ contract_version: 'actionviewmodel:v2' }).state).toBe('unavailable')
    expect(normalizeActionViewModel(raw({ action_id: '' })).reason).toBe('missing-action-id')
  })
  it('makes stale freshness explicit and does not invent a fetch id', () => {
    const model = normalizeActionViewModel(raw({ freshness: { label: 'stale' } }))
    expect(model.state).toBe('stale')
    expect(actionWorkbenchApi('ACT-1', 3)).toEqual({ url: 'crm.api.student_worklist.get_action_workbench', params: { action: 'ACT-1', expected_action_revision: 3 } })
  })
})
