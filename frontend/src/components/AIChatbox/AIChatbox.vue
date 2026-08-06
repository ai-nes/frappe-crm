<template>
  <ChatboxButton :is-open="isOpen" @toggle="isOpen = !isOpen" />
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
  { id: 2, role: 'user', text: __('Can you show me my open deals?') },
  {
    id: 3,
    role: 'assistant',
    text: __('Sure, pulling up your open deals now...'),
  },
])

const suggestions = [
  __('Show my open deals'),
  __('List today’s tasks'),
  __('Any leads assigned to me?'),
]

const cannedReplies = [
  __("Got it, I'm looking into that now."),
  __('Thanks for the details, one moment please.'),
  __('Noted. I will follow up on this shortly.'),
]

let nextId = 4

function handleSend(text) {
  messages.value.push({ id: nextId++, role: 'user', text })

  const reply =
    cannedReplies[Math.floor(Math.random() * cannedReplies.length)]

  setTimeout(() => {
    messages.value.push({ id: nextId++, role: 'assistant', text: reply })
  }, 600)
}
</script>
