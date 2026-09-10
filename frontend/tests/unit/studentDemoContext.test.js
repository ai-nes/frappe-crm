import { describe, expect, it } from 'vitest'
import { normalizeStudentDemoContext } from '../../src/utils/studentDemoContext'

describe('student demo context', () => {
  it('keeps a staged response without demo_context empty and harmless', () => {
    expect(normalizeStudentDemoContext()).toMatchObject({
      campaign: null,
      event: null,
      scholarship: null,
      nextAction: null,
      activity: [],
      hasContent: false,
    })
  })

  it('retains the useful partial facts and falls back to the active decision', () => {
    const context = normalizeStudentDemoContext(
      { scholarship: { intent_type: 'Scholarship', notes: 'Mục tiêu học bổng: 50%' } },
      { activeAction: { actionType: 'Gọi phụ huynh', dueAt: '2026-08-28T09:00:00Z' } },
    )

    expect(context.scholarship).toMatchObject({
      label: 'Scholarship',
      notes: 'Mục tiêu học bổng: 50%',
    })
    expect(context.nextAction).toMatchObject({ summary: 'Gọi phụ huynh' })
    expect(context.hasContent).toBe(true)
  })

  it('normalizes safe full context and only forwards display activity fields', () => {
    const context = normalizeStudentDemoContext({
      campaign: { label: 'Open Day 2026', source: 'Facebook Ads', occurred_at: '2026-08-20T09:00:00Z' },
      event: { label: 'Open Day HCM', status: 'Checked-in', occurred_at: '2026-08-24T08:00:00Z' },
      scholarship: { label: 'Scholarship', importance: 'High', confidence: 90, notes: 'Mục tiêu học bổng: 50%' },
      next_action: { summary: 'Follow-up hồ sơ', due_at: '2026-08-28T09:00:00Z' },
      activity: [{ key: 'event-1', summary: 'Checked in at Open Day HCM', occurred_at: '2026-08-24T08:00:00Z', reference_docname: 'EVP-1' }],
    })

    expect(context.event.status).toBe('checked-in')
    expect(context.activity).toEqual([{
      key: 'event-1',
      summary: 'Checked in at Open Day HCM',
      occurredAt: '2026-08-24T08:00:00Z',
    }])
  })

  it('suppresses superseded or incomplete activity rows', () => {
    const context = normalizeStudentDemoContext({
      activity: [
        { key: 'old', summary: 'Old invitation', occurred_at: '2026-08-20T09:00:00Z', superseded: true },
        { key: 'missing-time', summary: 'Incomplete event' },
        { key: 'current', summary: 'Invited to Open Day HCM', occurred_at: '2026-08-22T09:00:00Z' },
      ],
    })

    expect(context.activity).toEqual([{
      key: 'current',
      summary: 'Invited to Open Day HCM',
      occurredAt: '2026-08-22T09:00:00Z',
    }])
  })
})
