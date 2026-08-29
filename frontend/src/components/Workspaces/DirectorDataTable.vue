<template>
  <div
    class="overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white"
    :aria-label="title || __('Bảng dữ liệu')"
  >
    <div class="overflow-x-auto">
      <table class="min-w-full text-xs sm:text-sm">
        <caption class="sr-only">{{ title || __('Bảng dữ liệu') }}</caption>
        <thead class="bg-surface-gray-2 text-left text-ink-gray-6 font-semibold uppercase tracking-wider text-[11px]">
          <tr>
            <th scope="col" class="px-4 py-2.5">{{ labelHeader }}</th>
            <th scope="col" class="px-4 py-2.5 text-right">{{ valueHeader }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-outline-gray-1">
          <tr
            v-for="point in points"
            :key="point.key"
            class="transition-colors hover:bg-surface-gray-1/60"
          >
            <th scope="row" class="px-4 py-2.5 text-left font-medium text-ink-gray-8">
              {{ point.label }}
            </th>
            <td class="px-4 py-2.5 text-right font-medium tabular-nums text-ink-gray-9">
              {{ formatValue(point.value) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: String,
  points: { type: Array, default: () => [] },
  unit: String,
  labelHeader: { type: String, default: () => __('Chỉ tiêu / Nhãn') },
  valueHeader: { type: String, default: () => __('Giá trị') },
})

const formatter = computed(
  () => new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }),
)

function formatValue(value) {
  if (value == null) return '—'
  return typeof value === 'number'
    ? `${formatter.value.format(value)}${props.unit === 'percent' ? '%' : ''}`
    : String(value)
}
</script>
