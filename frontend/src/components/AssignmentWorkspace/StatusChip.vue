<template>
  <span class="inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium" :class="classes">
    {{ assignmentWorkspaceStatusLabel(status) }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { assignmentWorkspaceStatusLabel } from '@/data/assignmentWorkspace'

const props = defineProps({ status: { type: String, default: '' } })
const classes = computed(() => ({
  'bg-green-50 text-green-700': props.status === 'healthy',
  'bg-orange-50 text-orange-700': props.status === 'unassigned' || props.status === 'needs_review',
  'bg-yellow-50 text-yellow-800': props.status === 'capacity_warning',
  'bg-gray-100 text-gray-700': props.status === 'placeholder_zone',
}))
</script>
