<template>
  <div class="space-y-3" aria-label="Call workbench">
    <p class="text-sm text-ink-gray-7">{{ __('Use the approved script. Dial manually through your authorized phone system.') }}</p>
    <div v-if="section?.body" class="rounded-md bg-surface-gray-2 p-3 text-sm whitespace-pre-wrap">{{ section.body }}</div>
  </div>
</template>
<script setup>
defineProps({ section: { type: Object, default: () => ({}) } })
</script>
