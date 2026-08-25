<template>
  <section class="border-b px-5 py-3" aria-label="Lifecycle">
    <div class="flex items-center justify-between gap-3 text-sm">
      <span class="font-semibold text-ink-gray-8">{{ __('Lifecycle') }}</span>
      <span v-if="loading" class="text-ink-gray-5" role="status">{{ __('Loading…') }}</span>
      <span v-else-if="error" class="truncate text-ink-red-3" role="alert">{{ error }}</span>
      <span v-else-if="context" class="font-medium text-ink-gray-7" :title="lifecycle.policy_version || undefined">
        {{ lifecycle.current_stage || lifecycle.stage || __('Unavailable') }}
      </span>
      <span v-else class="text-ink-gray-5">{{ __('Unavailable') }}</span>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  context: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const lifecycle = computed(() => props.context?.lifecycle || {})
</script>
