<template>
  <div
    class="fixed z-20 flex flex-col overflow-hidden rounded-lg border bg-surface-modal shadow-2xl transition-all"
    :class="
      expanded
        ? 'inset-8 h-auto w-auto'
        : 'bottom-20 right-5 h-[480px] w-[360px]'
    "
  >
    <div class="flex items-center justify-between border-b px-4 py-3">
      <div class="text-base font-semibold text-ink-gray-9">
        {{ __('AI Assistant') }}
      </div>
      <div class="flex items-center gap-1">
        <button
          class="flex h-6 w-6 items-center justify-center rounded text-ink-gray-6 hover:bg-surface-gray-2"
          @click="expanded = !expanded"
        >
          <MinimizeIcon v-if="expanded" class="h-4 w-4" />
          <MaximizeIcon v-else class="h-4 w-4" />
        </button>
        <button
          class="flex h-6 w-6 items-center justify-center rounded text-ink-gray-6 hover:bg-surface-gray-2"
          @click="$emit('close')"
        >
          <FeatherIcon name="x" class="h-4 w-4" />
        </button>
      </div>
    </div>
    <div ref="messageList" class="flex-1 space-y-3 overflow-y-auto px-4 py-3">
      <div
        v-for="message in messages"
        :key="message.id"
        class="flex"
        :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div
          class="max-w-[80%] rounded-lg px-3 py-2 text-sm"
          :class="
            message.role === 'user'
              ? 'bg-surface-gray-7 text-ink-white'
              : 'bg-surface-gray-2 text-ink-gray-9'
          "
        >
          {{ message.text }}
        </div>
      </div>
    </div>
    <div
      v-if="props.suggestions.length"
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
    <div class="flex items-center gap-2 border-t px-3 py-3">
      <FormControl
        v-model="draft"
        type="text"
        class="flex-1"
        :placeholder="__('Type a message...')"
        @keydown.enter="send"
      />
      <Button variant="solid" :label="__('Send')" @click="send" />
    </div>
  </div>
</template>
<script setup>
import { nextTick, ref, watch } from 'vue'
import { Button, FeatherIcon, FormControl } from 'frappe-ui'
import MaximizeIcon from '@/components/Icons/MaximizeIcon.vue'
import MinimizeIcon from '@/components/Icons/MinimizeIcon.vue'

const props = defineProps({
  messages: {
    type: Array,
    default: () => [],
  },
  suggestions: {
    type: Array,
    default: () => [],
  },
})
const emit = defineEmits(['close', 'send'])

const draft = ref('')
const messageList = ref(null)
const expanded = ref(false)

function sendText(text) {
  emit('send', text)
}

function send() {
  const text = draft.value.trim()
  if (!text) return
  sendText(text)
  draft.value = ''
}

watch(
  () => props.messages.length,
  () => {
    nextTick(() => {
      if (messageList.value) {
        messageList.value.scrollTop = messageList.value.scrollHeight
      }
    })
  },
)
</script>
