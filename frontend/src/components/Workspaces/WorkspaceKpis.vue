<template>
  <section v-if="items.length" class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" :aria-label="__('Workspace summary')">
    <component
      :is="item.drilldown ? 'button' : 'article'"
      v-for="item in items"
      :key="item.key || item.label"
      class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 text-left"
      :class="item.drilldown ? 'transition hover:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-5' : ''"
      :type="item.drilldown ? 'button' : undefined"
      @click="item.drilldown && $emit('drilldown', item)"
    >
      <div class="flex items-start justify-between gap-2">
        <p class="text-sm text-ink-gray-6">{{ __(item.label) }}</p>
        <span v-if="item.definition" class="text-xs text-ink-gray-5" :title="item.definition" aria-label="Definition">ⓘ</span>
      </div>
      <p class="mt-2 text-2xl font-semibold tabular-nums text-ink-gray-9">{{ displayValue(item) }}</p>
      <p v-if="item.sourceUpdatedAt" class="mt-2 text-xs text-ink-gray-5">{{ __('Updated {0}', [formatTimestamp(item.sourceUpdatedAt)]) }}</p>
      <p v-else-if="item.definition" class="mt-2 text-xs text-ink-gray-5">{{ item.definition }}</p>
    </component>
  </section>
</template>

<script setup>
defineProps({ items: { type: Array, default: () => [] } })
defineEmits(['drilldown'])
function displayValue(item) { return item.value === 0 ? '0' : item.value ?? '—' }
function formatTimestamp(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}
</script>
