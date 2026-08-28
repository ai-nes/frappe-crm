<template>
  <form class="flex flex-wrap items-end gap-3 border-b border-outline-gray-2 bg-surface-white px-3 py-3 sm:px-5" @submit.prevent>
    <label v-for="filter in filters" :key="filter.key" class="min-w-36 flex-1 text-sm sm:max-w-56">
      <span class="mb-1 block font-medium text-ink-gray-7">{{ __(filter.label) }}</span>
      <select
        :value="modelValue?.[filter.key] ?? ''"
        class="form-control w-full"
        :aria-label="__(filter.label)"
        @change="update(filter, $event.target.value)"
      >
        <option value="">{{ __('All') }}</option>
        <option v-for="option in filter.options || []" :key="optionValue(option)" :value="optionValue(option)">
          {{ optionLabel(option) }}
        </option>
      </select>
    </label>
    <slot name="actions" />
  </form>
</template>

<script setup>
const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  filters: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'change'])

function optionValue(option) { return typeof option === 'object' ? option.value : option }
function optionLabel(option) { return typeof option === 'object' ? option.label : option }
function update(filter, value) {
  const allowed = (filter.options || []).map(optionValue)
  const nextValue = !value || !allowed.length || allowed.includes(value) ? value : ''
  const next = { ...props.modelValue, [filter.key]: nextValue }
  emit('update:modelValue', next)
  emit('change', next)
}
</script>
