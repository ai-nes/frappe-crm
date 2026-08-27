<template>
  <ChatboxButton v-if="!isOpen" @toggle="openChat" />
  <ChatboxPanel
    v-else
    :messages="messages"
    :suggestions="suggestions"
    :is-loading="isLoading"
    :error="errorMessage"
    :history="history"
    :history-loading="historyLoading"
    :history-error="historyError"
    :session-id="sessionId"
    @close="closeChat"
    @send="handleSend"
    @cancel="cancelRequest"
    @retry="retryMessage"
    @new-chat="startNewChat"
    @load-history="loadConversation"
  />
</template>

<script setup>
import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'
import ChatboxButton from '@/components/AIChatbox/ChatboxButton.vue'
import ChatboxPanel from '@/components/AIChatbox/ChatboxPanel.vue'
import {
  applyUIStreamEvent,
  consumeUIStream,
} from '@/components/AIChatbox/stream'

const BFF_METHODS = Object.freeze({
  stream: '/api/method/crm.api.copilot_delegation.stream_chat',
  list: '/api/method/crm.api.copilot_delegation.list_conversations',
  get: '/api/method/crm.api.copilot_delegation.get_conversation',
})

const isOpen = ref(false)
const messages = ref([])
const sessionId = ref(null)
const history = ref([])
const historyLoading = ref(false)
const historyError = ref('')
const errorMessage = ref('')
// A request run is compared by object identity while stream events arrive.
// `ref()` deep-converts assigned objects to proxies, making
// `activeRun.value === run` false and discarding every text delta as stale.
const activeRun = shallowRef(null)
let nextId = 1

const suggestions = [
  __('Show my open deals'),
  __('List today’s tasks'),
  __('Any leads assigned to me?'),
]

const isLoading = computed(() => Boolean(activeRun.value))

function openChat() {
  isOpen.value = true
  void refreshHistory()
}

function closeChat() {
  cancelRequest()
  isOpen.value = false
}

function startNewChat() {
  cancelRequest()
  sessionId.value = null
  messages.value = []
  errorMessage.value = ''
}

function csrfToken() {
  if (typeof window === 'undefined') return 'fetch'
  return window.csrf_token || window.frappe?.csrf_token || 'fetch'
}

function requestHeaders(accept = 'application/json') {
  return {
    Accept: accept,
    'X-Frappe-CSRF-Token': csrfToken(),
  }
}

function unwrapMessage(payload) {
  return payload && Object.prototype.hasOwnProperty.call(payload, 'message')
    ? payload.message
    : payload
}

async function responseError(response) {
  let detail = ''
  try {
    const payload = await response.clone().json()
    const body = unwrapMessage(payload)
    detail =
      body?.message ||
      body?.detail ||
      body?.error ||
      payload?._server_messages ||
      ''
  } catch {
    try {
      detail = await response.clone().text()
    } catch {
      // Keep the default status-based message.
    }
  }

  if (typeof detail === 'string') {
    try {
      const parsed = JSON.parse(detail)
      detail = parsed?.[0]?.message || parsed?.message || detail
    } catch {
      // Keep the plain response text when it is not JSON encoded.
    }
  }

  return String(detail || `${__('Request failed')} (${response.status})`)
}

async function requestJSON(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...requestHeaders(),
      ...(options.headers || {}),
    },
  })
  if (!response.ok) throw new Error(await responseError(response))
  return unwrapMessage(await response.json())
}

function getErrorMessage(error, fallback) {
  if (error?.message) return error.message
  if (error?.messages?.length) return error.messages[0]
  return fallback
}

function normalizeHistory(payload) {
  const body = payload?.data || payload || {}
  const items = body.threads || body.conversations || body.items || []
  return Array.isArray(items)
    ? items
        .map((item) => ({
          id: item.id || item.sessionId || item.session_id,
          title: item.title || item.name || __('Untitled conversation'),
          updatedAt: item.updatedAt || item.updated_at || item.modified || '',
        }))
        .filter((item) => item.id)
    : []
}

function normalizeMessages(payload) {
  const body = payload?.data || payload || {}
  const rawMessages = Array.isArray(body.messages) ? body.messages : []
  return rawMessages
    .map((message, index) => {
      const text = Array.isArray(message.parts)
        ? message.parts
            .filter((part) => part?.type === 'text')
            .map((part) => part.text || '')
            .join('')
        : message.text || message.content || ''
      return {
        id: message.id || `${message.role || 'message'}-${index}`,
        role: message.role === 'user' ? 'user' : 'assistant',
        text,
      }
    })
    .filter((message) => message.text)
}

async function refreshHistory() {
  historyLoading.value = true
  historyError.value = ''
  try {
    history.value = normalizeHistory(await requestJSON(BFF_METHODS.list))
  } catch (error) {
    historyError.value = getErrorMessage(
      error,
      __('Unable to load conversation history.'),
    )
  } finally {
    historyLoading.value = false
  }
}

async function loadConversation(conversation) {
  const id = typeof conversation === 'string' ? conversation : conversation?.id
  if (!id) return

  cancelRequest()
  historyLoading.value = true
  historyError.value = ''
  errorMessage.value = ''
  try {
    const query = new URLSearchParams({ session_id: id })
    const payload = await requestJSON(`${BFF_METHODS.get}?${query}`)
    const body = payload?.data || payload || {}
    sessionId.value = body.sessionId || body.session_id || id
    messages.value = normalizeMessages(payload)
  } catch (error) {
    historyError.value = getErrorMessage(
      error,
      __('Unable to load this conversation.'),
    )
  } finally {
    historyLoading.value = false
  }
}

function toApiMessages(source) {
  return source
    .filter((message) => message.role === 'user' || message.role === 'assistant')
    .filter(
      (message) =>
        message.text ||
        message.role === 'user' ||
        message.envelope?.answer,
    )
    .map((message, index) => ({
      id: String(message.id || `${message.role}-${index}`),
      role: message.role,
      parts: [
        {
          type: 'text',
          text: message.text || message.envelope?.answer || '',
        },
      ],
    }))
    .filter((message) => message.parts[0].text)
}

function findMessage(id) {
  return messages.value.find((message) => message.id === id)
}

function createAssistantMessage(prompt) {
  const message = {
    id: `assistant-${nextId++}`,
    role: 'assistant',
    text: '',
    streaming: true,
    retryText: prompt,
    error: '',
    retryable: false,
    approval: null,
		activity: [],
	}
	messages.value.push(message)
	// Read it back through the reactive array. Vue retains the caller's raw
	// object on push, so mutating that reference during SSE consumption can
	// bypass the proxy and leave a visually empty assistant bubble.
	return messages.value[messages.value.length - 1]
}

function addUserMessage(prompt) {
  messages.value.push({
    id: `user-${nextId++}`,
    role: 'user',
    text: prompt,
  })
}

function handleSend(text) {
  const prompt = String(text || '').trim()
  if (!prompt || activeRun.value) return
  addUserMessage(prompt)
  void streamReply(prompt, createAssistantMessage(prompt))
}

function retryMessage(message) {
  if (activeRun.value || !message?.retryText) return
  errorMessage.value = ''
  message.text = ''
  message.error = ''
  message.retryable = false
  message.streaming = true
  void streamReply(message.retryText, message)
}

async function streamReply(prompt, message) {
	const controller = new AbortController()
	const run = {
    controller,
    assistantId: message.id,
    prompt,
    finished: false,
    cancelled: false,
	}
	activeRun.value = run
	errorMessage.value = ''
	const currentMessage = () => findMessage(run.assistantId)

  try {
    const body = {
      messages: toApiMessages(messages.value),
    }
    if (sessionId.value) body.id = sessionId.value

    const response = await fetch(BFF_METHODS.stream, {
      method: 'POST',
      credentials: 'same-origin',
      signal: controller.signal,
      headers: {
        ...requestHeaders('text/event-stream'),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
    if (!response.ok) throw new Error(await responseError(response))

	await consumeUIStream(response, (event) => {
		const target = currentMessage()
		if (!target) return
		applyUIStreamEvent(
			event,
			target,
			run,
			activeRun.value === run,
			(id) => {
				sessionId.value = id
			},
			() => {},
			() => {
				target.streaming = false
				if (activeRun.value === run) activeRun.value = null
			},
			(activity) => {
				if (!target.activity) target.activity = []
				target.activity.push(activity)
			},
		)
	})

    if (run.cancelled) return
    if (run.approvalRequired) {
      void refreshHistory()
      return
    }
    if (!run.finished) {
      throw new Error(__('The assistant stream ended before completion.'))
    }
	const target = currentMessage()
	if (target) target.streaming = false
	void refreshHistory()
	} catch (error) {
		if (run.cancelled || error?.name === 'AbortError') return
		const target = currentMessage()
		if (target) {
			target.streaming = false
			target.error = getErrorMessage(error, __('Unable to reach the assistant.'))
			target.retryable = true
			errorMessage.value = target.error
		}
  } finally {
    if (activeRun.value === run) activeRun.value = null
  }
}

function cancelRequest() {
  const run = activeRun.value
  if (!run) return

  run.cancelled = true
  activeRun.value = null
  run.controller.abort()

  const message = findMessage(run.assistantId)
  if (message) {
    message.streaming = false
    if (!message.text) {
      messages.value = messages.value.filter((item) => item.id !== message.id)
    }
  }
}

onBeforeUnmount(cancelRequest)
</script>
