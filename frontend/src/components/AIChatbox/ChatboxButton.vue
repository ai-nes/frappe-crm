<template>
  <button
    class="fixed bottom-5 right-5 z-20 flex h-12 w-12 items-center justify-center rounded-full bg-surface-gray-7 text-ink-white shadow-2xl transition-transform hover:scale-105 active:scale-95"
    @click="$emit('toggle')"
  >
    <CommentIcon class="h-5 w-5" />
  </button>
</template>
<script setup>
import CommentIcon from '@/components/Icons/CommentIcon.vue'

defineEmits(['toggle'])
</script>
