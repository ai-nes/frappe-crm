<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4" :aria-label="title || __('Analytics')">
    <div class="flex flex-wrap items-start justify-between gap-2"><div><h2 class="font-semibold text-ink-gray-9">{{ title || __('Analytics') }}</h2><p v-if="definition" class="mt-1 text-sm text-ink-gray-6">{{ definition }}</p></div><span v-if="sourceUpdatedAt" class="text-xs text-ink-gray-5">{{ __('Updated {0}', [sourceUpdatedAt]) }}</span></div>
    <p v-if="suppressed" class="mt-5 rounded bg-surface-gray-1 p-3 text-sm text-ink-gray-6">{{ suppressed }}</p>
    <p v-else-if="!series.length" class="mt-5 text-sm text-ink-gray-5">{{ emptyMessage || __('No aggregate data is available for these filters.') }}</p>
    <div v-else class="mt-4 overflow-x-auto"><table class="w-full text-sm"><thead class="text-left text-ink-gray-6"><tr><th class="pb-2 font-medium">{{ __('Period') }}</th><th class="pb-2 text-right font-medium">{{ __('Value') }}</th></tr></thead><tbody class="divide-y divide-outline-gray-1"><tr v-for="point in series" :key="point.label || point.period"><td class="py-2 text-ink-gray-8">{{ point.label || point.period }}</td><td class="py-2 text-right tabular-nums text-ink-gray-8">{{ point.value ?? '—' }}</td></tr></tbody></table></div>
  </section>
</template>
<script setup>
defineProps({ title: String, definition: String, sourceUpdatedAt: String, series: { type: Array, default: () => [] }, suppressed: String, emptyMessage: String })
</script>
