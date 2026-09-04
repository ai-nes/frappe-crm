import { describe, expect, it } from 'vitest'
import {
  ACTION_VIEW_MODEL_CONTRACT,
  actionWorkbenchApi,
  normalizeActionViewModel,
  NBA_TASK_LABEL,
  nbaTaskNoun,
  operationCreatesTask,
  nbaTaskFromDecision,
  recommendationArtifacts,
} from '../../src/utils/actionWorkbench'

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

describe('NBA Task semantics', () => {
  const aiPayload = Object.freeze({ actionId: 'ACT-1', channel: 'phone', timing: 't0', objective: 'Call' })

  it('presents the CRM Action Item consistently as an NBA Task', () => {
    expect(NBA_TASK_LABEL).toBe('NBA Task')
    expect(nbaTaskNoun('CRM Action Item')).toBe('NBA Task')
    expect(nbaTaskNoun('CRM Action')).toBe('NBA Task')
    expect(nbaTaskNoun('')).toBe('NBA Task')
  })

  it('creates a Task only for accepting operations', () => {
    expect(operationCreatesTask('ACCEPT')).toBe(true)
    expect(operationCreatesTask('ACCEPT_WITH_CHANGES')).toBe(true)
    for (const operation of ['REJECT', 'DEFER', 'DISMISS']) {
      expect(operationCreatesTask(operation)).toBe(false)
      expect(nbaTaskFromDecision({ operation, aiPayload })).toBeNull()
    }
  })

  it('builds Task values from human overrides without mutating the AI proposal', () => {
    const delta = { channel: 'zalo' }
    const task = nbaTaskFromDecision({ operation: 'ACCEPT_WITH_CHANGES', aiPayload, delta })
    expect(task).toMatchObject({ actionId: 'ACT-1', channel: 'zalo', timing: 't0' })
    expect(aiPayload.channel).toBe('phone')
  })

  it('keeps the AI proposal and the human Task draft as separate artifacts', () => {
    const artifacts = recommendationArtifacts({
      operation: 'ACCEPT_WITH_CHANGES',
      aiPayload,
      delta: { timing: 't1' },
    })
    expect(artifacts.proposal.timing).toBe('t0')
    expect(artifacts.task.timing).toBe('t1')
    expect(artifacts.changedKeys).toEqual(['timing'])
    expect(artifacts.proposal).not.toBe(aiPayload)
  })
})
