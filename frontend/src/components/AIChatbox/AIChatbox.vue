<template>
  <ChatboxButton v-if="!isOpen" @toggle="isOpen = true" />
  <ChatboxPanel
    v-if="isOpen"
    :messages="messages"
    :suggestions="suggestions"
    @close="isOpen = false"
    @send="handleSend"
  />
</template>
<script setup>
import { ref } from 'vue'
import ChatboxButton from '@/components/AIChatbox/ChatboxButton.vue'
import ChatboxPanel from '@/components/AIChatbox/ChatboxPanel.vue'

const isOpen = ref(false)

const messages = ref([
  { id: 1, role: 'assistant', text: __('Hi! How can I help you today?') },
])

const suggestions = [
  __('Show my open deals'),
  __('List today’s tasks'),
  __('Any leads assigned to me?'),
]

const cannedReplies = [
  __("Got it, I'm looking into that now.\n\nHere is a quick summary:\n- Checked your **open deals**\n- Cross-referenced today's tasks\n\nLet me know if you'd like more detail."),
  __('Thanks for the details, one moment please.\n\n```\nchecking CRM records...\n```'),
  __('Noted. I will follow up on this shortly.'),
]

let nextId = 2

function handleSend(text) {
  messages.value.push({ id: nextId++, role: 'user', text })

  const reply =
    cannedReplies[Math.floor(Math.random() * cannedReplies.length)]

  const assistantMessage = {
    id: nextId++,
    role: 'assistant',
    text: '',
    streaming: true,
  }
  messages.value.push(assistantMessage)

  setTimeout(() => streamReply(assistantMessage, reply), 400)
}

function streamReply(message, fullText) {
  const tokens = fullText.split(/(\s+)/)
  let i = 0

  const interval = setInterval(() => {
    message.text += tokens[i]
    i++
    if (i >= tokens.length) {
      clearInterval(interval)
      message.streaming = false
    }
  }, 40)
}
</script>
