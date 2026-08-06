<template>
  <button
    class="fixed bottom-5 right-5 z-20 flex h-24 w-24 items-center justify-center rounded-full shadow-2xl transition-transform hover:scale-105 active:scale-95"
    @click="$emit('toggle')"
  >
    <img src="/chatbox-button.png" class="h-48 w-48" alt="" />
  </button>
</template>
<script setup>
defineEmits(['toggle'])
</script>
