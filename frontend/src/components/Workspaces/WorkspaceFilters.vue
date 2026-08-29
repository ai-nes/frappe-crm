<template>
  <div class="border-b border-outline-gray-2/80 bg-surface-white px-4 py-2.5 sm:px-6 shadow-xs">
    <form class="flex flex-wrap items-end gap-3" @submit.prevent>
      <div
        v-for="filter in filters"
        :key="filter.key"
        class="min-w-36 max-w-56 flex-1 text-sm"
      >
        <div class="mb-1 flex items-center justify-between gap-1">
          <span class="text-xs font-medium text-ink-gray-6">
            {{ __(filter.label || filter.key) }}
          </span>
          <span
            v-if="filter.coverageWarning || filter.warning"
            class="inline-flex items-center text-amber-600"
            :title="filter.coverageWarning || filter.warning"
            role="status"
          >
            <FeatherIcon name="alert-circle" class="size-3.5" />
          </span>
        </div>
        <div class="relative">
          <select
            :value="modelValue?.[filter.key] ?? ''"
            class="h-8 w-full appearance-none rounded-md border border-outline-gray-2 bg-surface-white pl-2.5 pr-7 text-xs sm:text-sm font-medium text-ink-gray-8 transition-colors hover:border-outline-gray-3 focus:border-outline-gray-4 focus:outline-none focus:ring-1 focus:ring-outline-gray-4"
            :aria-label="__(filter.label || filter.key)"
            @change="update(filter, $event.target.value)"
          >
            <option value="">{{ __('Tất cả') }}</option>
            <option
              v-for="option in filter.options || []"
              :key="optionValue(option)"
              :value="optionValue(option)"
              :disabled="optionDisabled(option)"
            >
              {{ optionLabel(option) }}
            </option>
          </select>
          <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-ink-gray-5">
            <FeatherIcon name="chevron-down" class="size-3.5" />
          </div>
        </div>
      </div>
      <div v-if="hasActiveFilters" class="flex items-center pb-0.5">
        <Button
          variant="ghost"
          size="sm"
          iconLeft="x"
          :label="__('Xóa bộ lọc')"
          @click="clearAll"
        />
      </div>
      <slot name="actions" />
    </form>
  </div>
</template>

<script setup>
import { Button, FeatherIcon } from 'frappe-ui'
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  filters: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'change'])

const hasActiveFilters = computed(() =>
  Object.values(props.modelValue || {}).some((v) => v !== '' && v != null),
)

function optionValue(option) {
  return typeof option === 'object' ? option.value : option
}
function optionLabel(option) {
  return typeof option === 'object' ? option.label : option
}
function optionDisabled(option) {
  return typeof option === 'object' && option.disabled === true
}

function update(filter, value) {
  const allowed = (filter.options || [])
    .filter((option) => !optionDisabled(option))
    .map(optionValue)
  const nextValue =
    !value || !allowed.length || allowed.includes(value) ? value : ''
  const next = { ...props.modelValue, [filter.key]: nextValue }
  emit('update:modelValue', next)
  emit('change', next)
}

function clearAll() {
  const next = {}
  for (const filter of props.filters) {
    next[filter.key] = ''
  }
  emit('update:modelValue', next)
  emit('change', next)
}
</script>
