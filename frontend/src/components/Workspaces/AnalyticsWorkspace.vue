<template>
  <section class="space-y-4" :aria-label="title || __('Phân tích')">
    <header
      v-if="sourceUpdatedAt || title"
      class="flex flex-wrap items-center justify-between gap-2 px-1"
    >
      <h2
        v-if="title"
        class="text-xs font-semibold uppercase tracking-wider text-ink-gray-5"
      >
        {{ title }}
      </h2>
      <div
        v-if="sourceUpdatedAt"
        class="ml-auto flex items-center gap-1.5 text-xs text-ink-gray-5"
      >
        <FeatherIcon name="clock" class="size-3.5" />
        <span>{{ __('Cập nhật: {0}', [formatTimestamp(sourceUpdatedAt)]) }}</span>
      </div>
    </header>

    <div
      v-if="suppressed"
      class="flex items-start gap-2.5 rounded-xl border border-amber-200/60 bg-amber-50/70 p-4 text-sm text-amber-900 shadow-xs"
      role="status"
    >
      <FeatherIcon name="shield" class="size-4 shrink-0 text-amber-600 mt-0.5" />
      <span>{{ suppressed }}</span>
    </div>

    <div
      v-else-if="!series.length"
      class="flex flex-col items-center justify-center rounded-xl border border-outline-gray-2/80 bg-surface-white p-12 text-center text-sm text-ink-gray-5 shadow-xs"
    >
      <FeatherIcon name="pie-chart" class="size-8 text-ink-gray-4 mb-2 opacity-50" />
      <p>{{ emptyMessage || __('Chưa có dữ liệu phân tích cho bộ lọc này.') }}</p>
    </div>

    <div v-else class="grid gap-4 lg:grid-cols-2">
      <DirectorChartCard
        v-for="metric in series"
        :key="metric.metricId || metric.label"
        :metric="metric"
        :definition="definition"
        :suppressed="suppressed"
        :empty-message="emptyMessage"
      />
    </div>
  </section>
</template>

<script setup>
import { FeatherIcon } from 'frappe-ui'
import DirectorChartCard from './DirectorChartCard.vue'

const props = defineProps({
  title: String,
  definition: [String, Object],
  sourceUpdatedAt: String,
  series: { type: Array, default: () => [] },
  suppressed: String,
  emptyMessage: String,
})

function formatTimestamp(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? String(value)
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(date)
}
</script>
