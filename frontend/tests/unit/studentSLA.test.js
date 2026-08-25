import { describe, expect, it } from 'vitest'
import {
  buildPauseSLAPayload,
  buildResumeSLAPayload,
  createStudentSLACommandId,
  formatStudentSLADate,
  isStaleStudentSLAError,
  slaStatusPresentation,
} from '../../src/utils/studentSLA'

describe('student SLA UI helpers', () => {
  it('builds only the server command fields for pause and resume', () => {
    expect(buildPauseSLAPayload({ attempt: 'SLA-1', reasonCode: ' Waiting ', revision: 4 })).toEqual({ attempt: 'SLA-1', reason_code: 'Waiting', expected_revision: 4 })
    expect(buildResumeSLAPayload({ attempt: 'SLA-1', revision: 5 })).toEqual({ attempt: 'SLA-1', expected_revision: 5 })
  })

  it('creates a fresh command identifier for every submit', () => {
    expect(createStudentSLACommandId()).not.toBe(createStudentSLACommandId())
  })

  it('presents SLA state without exposing event payload data', () => {
    expect(slaStatusPresentation('breached')).toEqual({ label: 'Breached', theme: 'red' })
    expect(slaStatusPresentation('unknown')).toEqual({ label: 'unknown', theme: 'gray' })
  })

  it('recognizes stale command errors and readable dates', () => {
    expect(isStaleStudentSLAError({ messages: ['STALE_REVISION'] })).toBe(true)
    expect(isStaleStudentSLAError({ status: 409 })).toBe(true)
    expect(formatStudentSLADate(null)).toBe('Not scheduled')
    expect(formatStudentSLADate('bad date')).toBe('Unavailable')
    expect(formatStudentSLADate('2026-08-25T10:30:00Z', 'en-GB')).toContain('25')
  })
})
