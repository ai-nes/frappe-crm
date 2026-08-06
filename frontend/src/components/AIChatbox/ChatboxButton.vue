<template>
  <button
    class="fixed bottom-5 right-5 z-20 flex h-12 w-12 items-center justify-center rounded-full bg-ink-gray-9 text-ink-white shadow-2xl transition-transform hover:scale-105 active:scale-95"
    @click="$emit('toggle')"
  >
    <CommentIcon v-if="!isOpen" class="h-5 w-5" />
    <FeatherIcon v-else name="x" class="h-5 w-5" />
  </button>
</template>
<script setup>
import CommentIcon from '@/components/Icons/CommentIcon.vue'
import { FeatherIcon } from 'frappe-ui'

defineProps({
  isOpen: {
    type: Boolean,
    default: false,
  },
})
defineEmits(['toggle'])
</script>
