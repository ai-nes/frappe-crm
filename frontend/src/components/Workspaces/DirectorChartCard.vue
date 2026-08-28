<template>
  <article
    class="flex flex-col justify-between rounded-xl border border-outline-gray-2/80 bg-surface-white shadow-xs transition-all duration-150"
    :aria-labelledby="headingId"
  >
    <header class="flex items-center justify-between border-b border-outline-gray-1 px-5 py-3.5">
      <h3 :id="headingId" class="text-sm font-semibold text-ink-gray-9">
        {{ title || metric.label || __('Biểu đồ') }}
      </h3>
      <Button
        variant="subtle"
        size="sm"
        :iconLeft="showTable ? 'bar-chart-2' : 'table'"
        :label="showTable ? __('Xem biểu đồ') : __('Xem bảng dữ liệu')"
        :aria-expanded="showTable"
        :aria-controls="tableId"
        @click="showTable = !showTable"
      />
    </header>

    <div class="flex-1 p-5">
      <div
        v-if="metric.suppressed || suppressed"
        class="flex items-start gap-2.5 rounded-lg border border-amber-200/60 bg-amber-50/70 p-4 text-sm text-amber-900"
        role="status"
      >
        <FeatherIcon name="shield" class="size-4 shrink-0 text-amber-600 mt-0.5" />
        <span>{{ metric.suppressed || suppressed }}</span>
      </div>

      <div
        v-else-if="!points.length"
        class="flex flex-col items-center justify-center py-12 text-center text-sm text-ink-gray-5"
      >
        <FeatherIcon name="bar-chart" class="size-8 text-ink-gray-4 mb-2 opacity-50" />
        <p>{{ metric.emptyMessage || emptyMessage || __('Chưa có dữ liệu tổng hợp cho bộ lọc này.') }}</p>
      </div>

      <template v-else>
        <div v-show="!showTable" class="h-64 sm:h-72 w-full" aria-hidden="true">
          <DonutChart v-if="chartType === 'donut'" :config="donutConfig" />
          <NumberChart v-else-if="chartType === 'number'" :config="numberConfig" />
          <AxisChart v-else :config="axisConfig" />
        </div>

        <div :id="tableId" :class="showTable ? 'block' : 'sr-only'">
          <DirectorDataTable
            :title="title || metric.label"
            :points="points"
            :unit="metric.unit || unit"
          />
        </div>
      </template>
    </div>
  </article>
</template>

<script setup>
import { AxisChart, Button, DonutChart, FeatherIcon, NumberChart } from 'frappe-ui'
import { computed, ref } from 'vue'
import DirectorDataTable from './DirectorDataTable.vue'

const props = defineProps({
  metric: { type: Object, default: () => ({}) },
  title: String,
  definition: [String, Object],
  unit: String,
  suppressed: String,
  emptyMessage: String,
})

const showTable = ref(false)
const uid = `director-chart-${Math.random().toString(36).slice(2)}`
const headingId = `${uid}-heading`
const tableId = `${uid}-table`

const points = computed(() =>
  Array.isArray(props.metric.points)
    ? props.metric.points.map((point, index) => ({
        key: point.key || `${point.label || point.period || 'point'}-${index}`,
        label: point.label || point.period || __('Chưa xác định'),
        value: point.value,
      }))
    : [],
)

const chartType = computed(() => props.metric.chartType || props.metric.type || 'bar')
const chartData = computed(() =>
  points.value.map((point) => ({ label: point.label, value: point.value })),
)

const axisConfig = computed(() => ({
  data: chartData.value,
  title: props.title || props.metric.label || __('Biểu đồ'),
  xAxis: { key: 'label', type: 'category' },
  yAxis: { title: props.metric.unit || props.unit || __('Giá trị'), yMin: 0 },
  swapXY: chartData.value.length > 6,
  series: [
    {
      name: 'value',
      type:
        chartType.value === 'line' || chartType.value === 'area'
          ? chartType.value
          : 'bar',
    },
  ],
}))

const donutConfig = computed(() => ({
  data: chartData.value,
  title: props.title || props.metric.label || __('Biểu đồ'),
  categoryColumn: 'label',
  valueColumn: 'value',
}))

const numberConfig = computed(() => ({
  title: props.title || props.metric.label || __('Giá trị'),
  value: points.value[0]?.value || 0,
  suffix: props.metric.unit === 'percent' ? '%' : '',
}))
</script>
