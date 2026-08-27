<template>
  <StudentDemoContext :context="context" :loading="loading" />
</template>

<script setup>
import StudentDemoContext from '@/components/StudentDemoContext.vue'

defineProps({
  context: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})
</script>
