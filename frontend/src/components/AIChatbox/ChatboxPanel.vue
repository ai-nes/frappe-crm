<template>
  <div
    class="fixed inset-y-0 right-0 z-[101] flex flex-col overflow-hidden border-l bg-surface-modal shadow-2xl transition-all"
    :class="expanded ? '' : 'w-[380px]'"
    :style="expanded ? { left: sidebarWidth } : {}"
  >
    <div class="flex items-center justify-between border-b px-4 py-3">
      <div class="text-base font-semibold text-ink-gray-9">
        {{ __('AI Assistant') }}
      </div>
      <div class="flex items-center gap-1">
        <button
          class="flex h-6 w-6 items-center justify-center rounded text-ink-gray-6 hover:bg-surface-gray-2"
          :aria-label="__('Conversation history')"
          @click="showHistory = !showHistory"
        >
          <FeatherIcon name="clock" class="h-4 w-4" />
        </button>
        <button
          class="flex h-6 w-6 items-center justify-center rounded text-ink-gray-6 hover:bg-surface-gray-2"
          :aria-label="__('New conversation')"
          @click="$emit('new-chat')"
        >
          <FeatherIcon name="plus" class="h-4 w-4" />
        </button>
        <button
          class="flex h-6 w-6 items-center justify-center rounded text-ink-gray-6 hover:bg-surface-gray-2"
          :aria-label="expanded ? __('Collapse') : __('Expand')"
          @click="expanded = !expanded"
        >
          <MinimizeIcon v-if="expanded" class="h-4 w-4" />
          <MaximizeIcon v-else class="h-4 w-4" />
        </button>
        <button
          class="flex h-6 w-6 items-center justify-center rounded text-ink-gray-6 hover:bg-surface-gray-2"
          :aria-label="__('Close')"
          @click="$emit('close')"
        >
          <FeatherIcon name="x" class="h-4 w-4" />
        </button>
      </div>
    </div>

    <div v-if="showHistory" class="border-b bg-surface-gray-1 px-3 py-2">
      <div class="mb-1 flex items-center justify-between">
        <div class="text-xs font-semibold uppercase text-ink-gray-6">
          {{ __('Recent conversations') }}
        </div>
        <button
          class="text-xs text-ink-blue-5 hover:underline"
          @click="$emit('new-chat')"
        >
          {{ __('New') }}
        </button>
      </div>
      <div v-if="historyLoading" class="py-2 text-xs text-ink-gray-6">
        {{ __('Loading history...') }}
      </div>
      <div v-else-if="historyError" class="py-2 text-xs text-ink-red-4">
        {{ historyError }}
      </div>
      <div v-else-if="!history.length" class="py-2 text-xs text-ink-gray-6">
        {{ __('No previous conversations.') }}
      </div>
      <div v-else class="max-h-40 space-y-1 overflow-y-auto">
        <button
          v-for="conversation in history"
          :key="conversation.id"
          class="block w-full truncate rounded px-2 py-1.5 text-left text-sm text-ink-gray-8 hover:bg-surface-gray-2"
          :class="conversation.id === sessionId ? 'bg-surface-gray-2 font-medium' : ''"
          @click="selectConversation(conversation)"
        >
          {{ conversation.title }}
        </button>
      </div>
    </div>

    <div ref="messageList" class="flex-1 space-y-3 overflow-y-auto px-4 py-3">
      <div v-if="!messages.length && !isLoading" class="py-8 text-center text-sm text-ink-gray-6">
        {{ __('Ask about your CRM data or daily work to get started.') }}
      </div>
      <div
        v-for="message in messages"
        :key="message.id"
        class="flex"
        :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div
          v-if="message.role === 'user'"
          class="max-w-[80%] rounded-lg bg-surface-gray-7 px-3 py-2 text-sm text-ink-white"
        >
          {{ message.text }}
        </div>
        <div
          v-else
          class="max-w-[85%] rounded-lg bg-surface-gray-2 px-3 py-2 text-ink-gray-9"
          :class="message.error ? 'border border-ink-red-2' : ''"
        >
          <!-- eslint-disable vue/no-v-html -->
          <div
            v-if="message.text"
            class="prose-sm"
            v-html="renderMarkdown(message.text) + (message.streaming ? streamingCursor : '')"
          />
          <!-- eslint-enable vue/no-v-html -->
          <div v-if="message.error" class="mt-1 text-xs text-ink-red-4">
            {{ message.error }}
          </div>
          <div
            v-if="message.approval"
            class="mt-1 text-xs text-ink-amber-5"
          >
            {{ __('Approval is required before this action can continue.') }}
          </div>
          <button
            v-if="message.retryable"
            class="mt-2 text-xs font-medium text-ink-blue-5 hover:underline"
            @click="$emit('retry', message)"
          >
            {{ __('Retry') }}
          </button>
          <span
            v-if="message.streaming && !message.text"
            class="animate-pulse text-ink-gray-6"
          >
            {{ __('Thinking...') }}
          </span>
        </div>
      </div>
    </div>

    <div v-if="error && !messages.some((message) => message.error)" class="border-t px-3 py-2 text-xs text-ink-red-4">
      {{ error }}
    </div>

    <div
      v-if="!isLoading && suggestions.length"
      class="flex flex-wrap gap-1.5 border-t px-3 py-2"
    >
      <button
        v-for="suggestion in suggestions"
        :key="suggestion"
        class="rounded-full border px-2.5 py-1 text-xs text-ink-gray-7 hover:bg-surface-gray-2"
        @click="sendText(suggestion)"
      >
        {{ suggestion }}
      </button>
    </div>

    <form class="flex items-center gap-2 border-t px-3 py-3" @submit.prevent="send">
      <FormControl
        v-model="draft"
        type="text"
        class="flex-1"
        :disabled="isLoading"
        :placeholder="__('Type a message...')"
      />
      <Button
        v-if="isLoading"
        variant="subtle"
        :label="__('Stop')"
        @click="$emit('cancel')"
      />
      <Button
        v-else
        variant="solid"
        :label="__('Send')"
        :disabled="!draft.trim()"
        type="submit"
      />
    </form>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useStorage } from '@vueuse/core'
import { marked } from 'marked'
import { Button, FeatherIcon, FormControl } from 'frappe-ui'
import MaximizeIcon from '@/components/Icons/MaximizeIcon.vue'
import MinimizeIcon from '@/components/Icons/MinimizeIcon.vue'
import { sanitizeHTML } from '@/utils'

const streamingCursor = '<span class="animate-pulse">▍</span>'

function renderMarkdown(text) {
  return sanitizeHTML(marked.parse(text || ''))
}

const props = defineProps({
  messages: {
    type: Array,
    default: () => [],
  },
  suggestions: {
    type: Array,
    default: () => [],
  },
  isLoading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: String,
    default: '',
  },
  history: {
    type: Array,
    default: () => [],
  },
  historyLoading: {
    type: Boolean,
    default: false,
  },
  historyError: {
    type: String,
    default: '',
  },
  sessionId: {
    type: String,
    default: null,
  },
})

const emit = defineEmits([
  'close',
  'send',
  'cancel',
  'retry',
  'new-chat',
  'load-history',
])

const draft = ref('')
const messageList = ref(null)
const expanded = ref(false)
const showHistory = ref(false)

const isSidebarCollapsed = useStorage('isSidebarCollapsed', false)
const sidebarWidth = computed(() => (isSidebarCollapsed.value ? '3rem' : '220px'))

function sendText(text) {
  emit('send', text)
}

function send() {
  const text = draft.value.trim()
  if (!text || props.isLoading) return
  sendText(text)
  draft.value = ''
}

function selectConversation(conversation) {
  showHistory.value = false
  emit('load-history', conversation)
}

watch(
  () => [
    props.messages.length,
    props.messages.at(-1)?.text,
    props.isLoading,
    showHistory.value,
  ],
  () => {
    nextTick(() => {
      if (messageList.value) {
        messageList.value.scrollTop = messageList.value.scrollHeight
      }
    })
  },
)
</script>
