import {
  applyUIStreamEvent,
  consumeUIStream,
} from '@/components/AIChatbox/stream'
import { describe, expect, it } from 'vitest'
import { ref, shallowRef } from 'vue'

describe('AI chat stream terminal handling', () => {
  it('preserves the active run identity used to accept stream events', () => {
    const run = { assistantId: 'assistant-1' }

    expect(ref(run).value).not.toBe(run)
    expect(shallowRef(run).value).toBe(run)
  })

  it('stops consuming after a terminal event even if the transport stays open', async () => {
    const encoder = new TextEncoder()
    const events = []
    let reads = 0

    const response = {
      body: {
        getReader() {
          return {
            async read() {
              reads += 1
              if (reads === 1) {
                return {
                  done: false,
                  value: encoder.encode(
                    'data: {"type":"text-delta","delta":"Hello"}\n\n' +
                      'data: {"type":"finish"}\n\n',
                  ),
                }
              }
              return new Promise(() => {})
            },
            async cancel() {
              return undefined
            },
          }
        },
      },
    }

    await expect(
      Promise.race([
        consumeUIStream(response, (event) => events.push(event)),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('stream did not terminate')), 100),
        ),
      ]),
    ).resolves.toBeUndefined()

    expect(events.map((event) => event.type)).toEqual(['text-delta', 'finish'])
    expect(reads).toBe(1)
  })

  it('keeps finish state when a stale run completes', () => {
    const run = { finished: false }
    const message = { text: 'partial', streaming: true }

    applyUIStreamEvent(
      { type: 'finish' },
      message,
      run,
      false,
      () => {},
    )

    expect(run.finished).toBe(true)
    expect(message.streaming).toBe(true)
  })

  it('notifies the UI as soon as the terminal event arrives', () => {
    const run = { finished: false }
    const message = { text: 'complete', streaming: true }
    let finished = false

    applyUIStreamEvent(
      { type: 'finish' },
      message,
      run,
      true,
      () => {},
      () => {},
      () => {
        finished = true
      },
    )

    expect(finished).toBe(true)
    expect(run.finished).toBe(true)
    expect(message.streaming).toBe(false)
  })

  it('adopts the session and renders a complete event sequence', () => {
    const run = { finished: false }
    const message = { text: '', streaming: true }
    let sessionId = null

    applyUIStreamEvent(
      { type: 'start', messageMetadata: { session_id: 'session-1' } },
      message,
      run,
      true,
      (id) => {
        sessionId = id
      },
    )
    applyUIStreamEvent(
      { type: 'text-delta', delta: 'Hello' },
      message,
      run,
      true,
      () => {},
    )
    applyUIStreamEvent(
      { type: 'data-envelope', data: { answer: 'Hello' } },
      message,
      run,
      true,
      () => {},
    )
    applyUIStreamEvent(
      { type: 'finish' },
      message,
      run,
      true,
      () => {},
    )

    expect(sessionId).toBe('session-1')
    expect(message.text).toBe('Hello')
    expect(message.streaming).toBe(false)
    expect(run.finished).toBe(true)
  })

  it('renders approval as an intentional non-success terminal state', () => {
    const run = { finished: false, approvalRequired: false }
    const message = { text: '', streaming: true, approval: null }
    const approval = { proposal_id: 'proposal-1' }

    applyUIStreamEvent(
      { type: 'data-approval-required', data: approval },
      message,
      run,
      true,
      () => {},
      () => {},
    )

    expect(run.approvalRequired).toBe(true)
    expect(message.approval).toEqual(approval)
    expect(message.streaming).toBe(false)
  })

  it('forwards only the runtime activity event to the UI activity surface', () => {
    const run = { finished: false }
    const message = { text: '', streaming: true }
    let activity = null

    applyUIStreamEvent(
      {
        type: 'data-agent-activity',
        data: {
          phase: 'tool_end',
          resource: 'CRM Lead',
          operation: 'search',
          evidence_count: 3,
        },
      },
      message,
      run,
      true,
      () => {},
      () => {},
      () => {},
      (value) => {
        activity = value
      },
    )

    expect(activity).toEqual({
      phase: 'tool_end',
      resource: 'CRM Lead',
      operation: 'search',
      evidence_count: 3,
    })
  })

  it('stores a validated generic Student or School 360 envelope', () => {
    const run = { finished: false }
    const message = { text: '', streaming: true }
    applyUIStreamEvent(
      {
        type: 'data-360',
        data: {
          contract_version: '360-overview-v1',
          subject_type: 'school',
          subject_id: 'HS-1',
          summary: 'Có dữ liệu.',
          signals: [],
          risks: [],
          opportunities: [],
          recent_changes: [],
          data_quality: [],
          generated_at: '2026-09-07T10:00:00Z',
        },
      },
      message,
      run,
      true,
      () => {},
    )
    expect(message.overview360.subject_type).toBe('school')
    expect(message.overview360.subject_id).toBe('HS-1')
  })

  it('ignores malformed or unknown 360 envelopes', () => {
    const run = { finished: false }
    const message = { text: '', streaming: true, overview360: null }
    applyUIStreamEvent(
      {
        type: 'data-360',
        data: {
          contract_version: '360-overview-v1',
          subject_type: 'lead',
          subject_id: 'LEAD-1',
          summary: 'Sai subject.',
          signals: [], risks: [], opportunities: [], recent_changes: [],
          data_quality: [], generated_at: '2026-09-07T10:00:00Z',
        },
      },
      message,
      run,
      true,
      () => {},
    )
    expect(message.overview360).toBeNull()
  })

})
