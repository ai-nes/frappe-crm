<template>
  <button
    class="fixed bottom-5 right-5 z-20 flex h-12 w-12 items-center justify-center rounded-full bg-surface-white shadow-2xl transition-transform hover:scale-105 active:scale-95"
    @click="$emit('toggle')"
  >
    <img src="/chatbox-button.png" class="h-8 w-8" alt="" />
  </button>
</template>
<script setup>
defineEmits(['toggle'])
</script>
