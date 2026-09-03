<template>
  <div class="space-y-3" aria-label="Email workbench">
    <p class="text-sm text-ink-gray-7">{{ __('Edit only the wording fields authorized by the server, then submit for review.') }}</p>
    <div v-if="section?.body" class="rounded-md bg-surface-gray-2 p-3 text-sm whitespace-pre-wrap">{{ section.body }}</div>
  </div>
</template>
<script setup>
defineProps({ section: { type: Object, default: () => ({}) } })
</script>
