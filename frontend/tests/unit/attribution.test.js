import { describe, expect, it } from 'vitest'
import {
  attributionMetrics,
  attributionTimeline,
  buildAttributionPayload,
} from '../../src/utils/attribution'

describe('attribution helpers', () => {
  it('builds append-only campaign commands with a Student anchor', () => {
    expect(buildAttributionPayload({
      kind: 'campaign', record: 'CMP-1', student: ' STU-1 ', contact: '',
      source: 'Manual', notes: ' Booth visit ', idempotencyKey: 'key-1',
    })).toMatchObject({
      student: 'STU-1', crm_campaign: 'CMP-1', crm_contact: null,
      source: 'Manual', notes: 'Booth visit', idempotency_key: 'key-1',
      correlation_id: 'key-1', supersedes: null,
    })
  })

  it('builds an event correction without mutating prior evidence', () => {
    expect(buildAttributionPayload({
      kind: 'event', record: 'EVT-1', student: 'STU-1', status: 'Checked-in',
      occurredAt: '2026-08-25T10:00:00', idempotencyKey: 'key-2', supersedes: 'PART-1',
    })).toMatchObject({
      crm_event: 'EVT-1', student: 'STU-1', status: 'Checked-in',
      registered_at: '2026-08-25T10:00:00', supersedes: 'PART-1',
    })
  })

  it('only maps safe aggregate metrics and orders evidence deterministically', () => {
    expect(attributionMetrics({ metrics: { students: 4, enrolled: 1, student_name: 'Hidden' } }))
      .toEqual([{ label: 'Students', value: 4 }, { label: 'Enrolled', value: 1 }])
    expect(attributionTimeline({ timeline: [
      { name: 'A', student: 'STU-1', touched_at: '2026-08-24', source: 'Web' },
      { name: 'B', student: 'STU-2', touched_at: '2026-08-25', source: 'Event' },
    ] }).map((entry) => entry.name)).toEqual(['B', 'A'])
  })
})
