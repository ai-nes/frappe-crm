/**
 * Apply one UI Message Stream event without losing terminal state when a
 * previous request is finishing during a new-chat/cancel transition.
 *
 * The run object is deliberately marked finished even for a stale run. The
 * caller still gates visible message updates by `isCurrentRun`, but the
 * stream's own completion state must not be discarded by that UI race.
 */
export function applyUIStreamEvent(
  event,
  message,
  run,
  isCurrentRun,
  onSessionId,
  onApprovalRequired,
  onFinished,
  onActivity,
  onReasoning,
) {
  if (!event) return

  if (event.type === 'finish') {
    run.finished = true
    if (isCurrentRun) message.streaming = false
    onFinished?.()
    return
  }

  if (!isCurrentRun) return

  if (event.type === 'start') {
    const adoptedSessionId =
      event.messageMetadata?.session_id ||
      event.messageMetadata?.sessionId ||
      event.session_id
    if (adoptedSessionId) onSessionId(adoptedSessionId)
    const responseRunId = event.messageMetadata?.run_id
    if (responseRunId) run.runId = responseRunId
    return
  }

  if (event.type === 'text-delta') {
    message.text += event.delta || ''
    return
  }

  if (event.type === 'data-envelope') {
    const envelope =
      typeof event.data === 'string'
        ? JSON.parse(event.data || '{}')
        : event.data || {}
    message.envelope = envelope
    if (envelope.session_id || envelope.sessionId) {
      onSessionId(envelope.session_id || envelope.sessionId)
    }
    if (!message.text && envelope.answer) message.text = envelope.answer
    return
  }

  if (event.type === 'data-agent-activity') {
    const activity =
      typeof event.data === 'string'
        ? JSON.parse(event.data || '{}')
        : event.data || {}
    if (activity && typeof activity === 'object') onActivity?.(activity)
    return
  }

  if (event.type === 'data-agent-reasoning') {
    const reasoning =
      typeof event.data === 'string'
        ? JSON.parse(event.data || '{}')
        : event.data || {}
    if (reasoning && typeof reasoning === 'object') onReasoning?.(reasoning)
    return
  }

  if (event.type === 'data-student-analysis') {
    const brief =
      typeof event.data === 'string'
        ? JSON.parse(event.data || '{}')
        : event.data || {}
    message.analysisBrief = brief
    return
  }

  if (event.type === 'data-360' || event.type === 'data-student-360') {
    const overview =
      typeof event.data === 'string'
        ? (() => {
            try {
              return JSON.parse(event.data || '{}')
            } catch {
              return null
            }
          })()
        : event.data
    const itemArrays = ['signals', 'risks', 'opportunities', 'recent_changes']
    if (
      overview &&
      typeof overview === 'object' &&
      overview.contract_version === '360-overview-v1' &&
      (overview.subject_type === 'student' || overview.subject_type === 'school') &&
      typeof overview.subject_id === 'string' &&
      overview.subject_id &&
      typeof overview.summary === 'string' &&
      typeof overview.generated_at === 'string' &&
      Array.isArray(overview.data_quality) &&
      itemArrays.every((key) => Array.isArray(overview[key]))
    ) {
      message.overview360 = overview
    }
    return
  }

  if (event.type === 'data-approval-required') {
    run.approvalRequired = true
    if (isCurrentRun) {
      message.approval = event.data || {}
      message.streaming = false
      onApprovalRequired?.(event.data || {})
    }
    return
  }

  if (event.type === 'error') {
    throw new Error(event.error || event.message || 'The assistant returned an error.')
  }
}

export async function consumeUIStream(response, onEvent) {
  if (!response.body) throw new Error('The assistant stream was empty.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let dataLines = []
  let terminal = false

  const dispatch = () => {
    if (!dataLines.length) return

    const data = dataLines.join('\n')
    dataLines = []

    try {
      const event = JSON.parse(data)
      onEvent(event)
      terminal =
        event?.type === 'finish' ||
        event?.type === 'data-approval-required' ||
        event?.type === 'error'
    } catch {
      throw new Error('The assistant returned an invalid stream event.')
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (!line.trim()) {
        dispatch()
        if (terminal) break
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart())
      }
    }

    if (terminal) {
      void reader.cancel().catch(() => {})
      break
    }

    if (done) {
      if (buffer.startsWith('data:')) dataLines.push(buffer.slice(5).trimStart())
      dispatch()
      break
    }
  }
}
