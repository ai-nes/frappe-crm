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
