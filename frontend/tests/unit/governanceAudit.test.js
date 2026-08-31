import { describe, expect, it } from 'vitest'
import {
  buildAdditiveValuePayload,
  buildProposalPayload,
  governanceAffordances,
  governanceErrorState,
  normalizeImpact,
  normalizeTimeline,
} from '../../src/utils/governanceAudit'

describe('governance audit UI helpers', () => {
  it('builds a typed, correlated proposal DTO without local policy fields', () => {
    expect(buildProposalPayload({ doctype: ' CRM Campus ', docname: ' HN ', action: 'Rename', newValue: ' Ha Noi ', reason: 'Correct spelling', idempotencyKey: 'idem-1', expectedVersion: '4' })).toEqual({
      doctype: 'CRM Campus', docname: 'HN', action: 'Rename', new_value: 'Ha Noi', reason: 'Correct spelling',
      idempotency_key: 'idem-1', correlation_id: 'idem-1', expected_version: 4,
    })
  })

  it('builds the additive value command instead of a raw insert DTO', () => {
    expect(buildAdditiveValuePayload({ doctype: 'CRM Term', value: ' Budget ', idempotencyKey: 'idem-2' })).toEqual({
      doctype: 'CRM Term', value: 'Budget', reason: null, idempotency_key: 'idem-2', correlation_id: 'idem-2',
    })
  })

  it('exposes only role-scoped affordances', () => {
    expect(governanceAffordances({ roles: ['Marketing'] }, 'CRM Term')).toMatchObject({ canPropose: false, canApprove: true })
    expect(governanceAffordances({ roles: ['Lead Sales'] }, 'CRM Term')).toMatchObject({ canPropose: true, canApprove: true })
    expect(governanceAffordances({ roles: ['Marketing'] }, 'CRM Lead Source')).toMatchObject({ canPropose: true, canApprove: true })
  })

  it('normalizes server impact and preserves server redaction', () => {
    expect(normalizeImpact({ 'CRM Student.branch': 2, ignored: 'x' })).toEqual({ entries: [{ reference: 'CRM Student.branch', count: 2 }], total: 2 })
    expect(normalizeTimeline({ items: [{ name: 'E-1', event_type: 'Stage changed', reason: 'private', reason_redacted: true }] }).items[0]).toMatchObject({ id: 'E-1', reason: 'Reason restricted', redacted: true })
  })

  it('maps server conflicts and feature flags to explicit recovery states', () => {
    expect(governanceErrorState({ status: 409 }).kind).toBe('conflict')
    expect(governanceErrorState({ error_code: 'FEATURE_DISABLED' }).kind).toBe('disabled')
  })
})
