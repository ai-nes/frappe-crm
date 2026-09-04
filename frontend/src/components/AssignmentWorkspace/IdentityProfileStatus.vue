<template>
  <div class="flex flex-wrap items-center gap-1.5">
    <span
      class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
      :class="statusClass"
    >
      {{ statusLabel }}
    </span>
    <span v-if="row.crm_profile_label" class="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
      {{ row.crm_profile_label }}
    </span>
    <span v-else-if="row.role_state === 'platform_superuser'" class="rounded-full bg-violet-50 px-2 py-0.5 text-xs text-violet-700">
      {{ __('Platform superuser') }}
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ row: { type: Object, required: true } })

const statusLabel = computed(() =>
  props.row.status === 'healthy' ? __('Sẵn sàng') : __('Cần setup'),
)

const statusClass = computed(() =>
  props.row.status === 'healthy'
    ? 'bg-green-50 text-green-700'
    : 'bg-orange-50 text-orange-700',
)
</script>
