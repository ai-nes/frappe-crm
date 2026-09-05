<template>
  <span class="inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium" :class="classes">
    {{ assignmentWorkspaceStatusLabel(status) }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { assignmentWorkspaceStatusLabel, assignmentWorkspaceStatusTone } from '@/data/assignmentWorkspace'

const props = defineProps({ status: { type: String, default: '' } })
const toneClasses = {
  success: 'bg-green-50 text-green-700',
  warning: 'bg-orange-50 text-orange-700',
  caution: 'bg-yellow-50 text-yellow-800',
  neutral: 'bg-gray-100 text-gray-700',
}
const classes = computed(() => toneClasses[assignmentWorkspaceStatusTone(props.status)])
</script>
