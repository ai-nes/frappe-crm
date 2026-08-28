<template>
  <p v-if="definition || timestamp" class="text-xs text-ink-gray-5">
    <span v-if="definition">{{ definition }}</span>
    <span v-if="definition && timestamp"> · </span>
    <span v-if="timestamp">{{ __('Cập nhật') }} {{ formatDate(timestamp) }}</span>
  </p>
</template>

<script setup>
import { formatDate } from '@/utils'
defineProps({ definition: { type: String, default: '' }, timestamp: { type: String, default: '' } })
</script>
