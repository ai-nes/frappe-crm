<template>
  <div class="h-full w-full">
    <div
      v-if="item.type == 'number_chart'"
      class="flex h-full w-full rounded shadow overflow-hidden cursor-pointer"
    >
      <Tooltip :text="__(item.data.tooltip)">
        <NumberChart
          v-if="item.data"
          :key="index"
          class="!items-start"
          :config="item.data"
        />
      </Tooltip>
    </div>
    <div
      v-else-if="item.type == 'spacer'"
      class="rounded bg-surface-white h-full overflow-hidden text-ink-gray-5 flex items-center justify-center"
      :class="editing ? 'border border-dashed border-outline-gray-2' : ''"
    >
      {{ editing ? __('Spacer') : '' }}
    </div>
    <div
      v-else-if="item.type == 'axis_chart'"
      class="h-full w-full rounded-md bg-surface-white shadow"
    >
      <AxisChart v-if="axisChartConfig" :config="axisChartConfig" />
    </div>
    <div
      v-else-if="item.type == 'donut_chart'"
      class="h-full w-full rounded-md bg-surface-white shadow overflow-hidden"
    >
      <DonutChart v-if="item.data" :config="item.data" />
    </div>
    <div
      v-else-if="item.type == 'interest_card'"
      class="flex h-full w-full flex-col rounded-md border border-outline-gray-1 bg-surface-white p-4 shadow-sm"
    >
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0">
          <div class="truncate text-sm font-medium text-ink-gray-8">
            {{ item.data.title }}
          </div>
          <div class="mt-1 text-xs text-ink-gray-5">{{ item.data.code }}</div>
        </div>
        <Badge
          variant="subtle"
          :theme="item.data.theme || 'gray'"
          :label="item.data.trend"
        />
      </div>
      <div class="mt-3 flex items-end justify-between gap-2">
        <div class="text-2xl font-semibold text-ink-gray-9">
          {{ formatNumber(item.data.value) }}
        </div>
        <div class="text-xs text-ink-gray-5">{{ item.data.ratio }}</div>
      </div>
      <template v-if="item.data.readinessLevels">
        <div
          class="mt-3 flex h-2 overflow-hidden rounded-full bg-surface-gray-2"
          role="group"
          :aria-label="__('Readiness distribution from Level 0 to 4')"
        >
          <span
            v-for="level in item.data.readinessLevels"
            :key="level.level"
            :class="readinessLevelClass(level.level)"
            :style="{ width: `${level.share}%` }"
            :title="`Level ${level.level}: ${formatNumber(level.count)} Lead`"
            role="progressbar"
            aria-valuemin="0"
            :aria-valuemax="item.data.readinessTotal"
            :aria-valuenow="level.count"
            :aria-label="`Level ${level.level}: ${formatNumber(level.count)} Lead`"
          ></span>
        </div>
        <div class="mt-2 grid grid-cols-5 gap-1 text-center text-[10px]">
          <div v-for="level in item.data.readinessLevels" :key="level.level">
            <div class="text-ink-gray-5">L{{ level.level }}</div>
            <div class="font-medium text-ink-gray-8">{{ compactNumber(level.count) }}</div>
          </div>
        </div>
        <div class="mt-3 grid grid-cols-3 gap-2 border-t pt-3 text-[10px]">
          <Metric
            v-for="metric in item.data.operationalMetrics"
            :key="metric.label"
            :label="metric.label"
            :value="formatNumber(metric.value)"
            :tone="metricTone(metric.label, metric.value)"
          />
        </div>
      </template>
      <template v-else>
        <div
          class="mt-3 flex h-7 items-end gap-1"
          role="img"
          :aria-label="`Xu hướng ${item.data.title}: ${item.data.trend}`"
        >
          <span
            v-for="(point, pointIndex) in item.data.sparkline"
            :key="pointIndex"
            class="flex-1 rounded-sm"
            :class="interestAccent(item.data.color).bar"
            :style="{ height: `${sparkHeight(point, item.data.sparkline)}%` }"
          ></span>
        </div>
        <div
          class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-gray-2"
          role="progressbar"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="item.data.progress"
          :aria-label="`${item.data.title}: ${item.data.progress}% so với nhóm cao nhất`"
        >
          <div
            class="h-full rounded-full"
            :class="interestAccent(item.data.color).fill"
            :style="{ width: `${item.data.progress}%` }"
          ></div>
        </div>
      </template>
      <div v-if="!item.data.readinessLevels" class="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t pt-3 text-xs">
        <Metric
          v-for="metric in item.data.metrics"
          :key="metric.label"
          :label="metric.label"
          :value="formatNumber(metric.value)"
          :tone="metricTone(metric.label, metric.value)"
        />
      </div>
      <div class="mt-auto flex items-center justify-between gap-2 pt-3 text-xs">
        <span class="text-ink-gray-5">{{ __('Enrollment rate') }}</span>
        <span class="font-medium text-ink-gray-8">{{ item.data.conversion }}</span>
        <Button
          variant="ghost"
          size="sm"
          :label="__('View Leads')"
          @click="openInterestLeads"
        />
      </div>
    </div>
    <div
      v-else-if="item.type == 'conversion_funnel'"
      class="flex h-full w-full flex-col overflow-hidden rounded-md border border-outline-gray-1 bg-surface-white shadow-sm"
    >
      <div class="border-b px-4 py-3">
        <div class="text-base font-medium text-ink-gray-9">{{ item.data.title }}</div>
        <div class="mt-0.5 text-xs text-ink-gray-5">{{ item.data.subtitle }}</div>
      </div>
      <div class="flex flex-wrap gap-x-4 gap-y-1 border-b px-4 py-2 text-[10px] text-ink-gray-5">
        <span v-for="segment in item.data.legend" :key="segment.label" class="flex items-center gap-1.5">
          <i class="size-2 rounded-sm" :class="segment.class"></i>{{ segment.label }}
        </span>
      </div>
      <div class="min-h-0 flex-1 overflow-auto px-4 py-2">
        <div v-for="row in item.data.rows" :key="row.label" class="grid grid-cols-[9rem_1fr_4rem] items-center gap-3 border-b py-2.5 last:border-b-0">
          <div class="truncate text-xs font-medium text-ink-gray-8">{{ row.label }}</div>
          <div class="flex h-3 overflow-hidden rounded-full bg-surface-gray-2" role="group" :aria-label="row.ariaLabel">
            <span
              v-for="segment in row.segments"
              :key="segment.label"
              :class="segment.class"
              :style="{ width: `${segment.share}%` }"
              :title="`${segment.label}: ${formatNumber(segment.value)}`"
              role="progressbar"
              aria-valuemin="0"
              :aria-valuemax="row.total"
              :aria-valuenow="segment.value"
              :aria-label="`${segment.label}: ${formatNumber(segment.value)} Lead`"
            ></span>
          </div>
          <div class="text-right text-[10px] text-ink-gray-5">
            <b class="text-ink-gray-8">{{ formatNumber(row.enrolled) }}</b> / {{ formatNumber(row.total) }}
          </div>
        </div>
      </div>
    </div>
    <div
      v-else-if="item.type == 'overlap_heatmap'"
      class="flex h-full w-full flex-col overflow-hidden rounded-md border border-outline-gray-1 bg-surface-white shadow-sm"
    >
      <div class="border-b px-4 py-3">
        <div class="text-base font-medium text-ink-gray-9">{{ item.data.title }}</div>
        <div class="mt-0.5 text-xs text-ink-gray-5">{{ item.data.subtitle }}</div>
        <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-ink-gray-5">
          <span class="flex items-center gap-1">
            Ít
            <i class="size-2 rounded-sm bg-blue-100"></i>
            <i class="size-2 rounded-sm bg-blue-200"></i>
            <i class="size-2 rounded-sm bg-blue-300"></i>
            <i class="size-2 rounded-sm bg-blue-400"></i>
            <i class="size-2 rounded-sm bg-blue-500"></i>
            {{ item.data.symmetric ? 'Nhiều Lead trùng' : 'Nhiều Lead' }}
          </span>
          <span v-if="item.data.symmetric" class="flex items-center gap-1">
            <i class="size-2 rounded-sm bg-surface-gray-3"></i>
            Tổng Lead của nhóm (đường chéo)
          </span>
        </div>
      </div>
      <div class="min-h-0 flex-1 overflow-auto p-3">
        <table class="h-full w-full border-separate border-spacing-1 text-center text-[10px]">
          <thead>
            <tr>
              <th></th>
              <th v-for="label in item.data.labels" :key="label" scope="col" class="px-1 py-1 font-medium text-ink-gray-5">{{ label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in item.data.rows" :key="row.label">
              <th scope="row" class="whitespace-nowrap pr-2 text-left font-medium text-ink-gray-7">{{ row.label }}</th>
              <td
                v-for="(value, valueIndex) in row.values"
                :key="valueIndex"
                class="rounded px-2 py-2 font-medium"
                :class="item.data.symmetric && valueIndex === rowIndex ? 'bg-surface-gray-3 text-ink-gray-8' : item.data.symmetric && valueIndex < rowIndex ? 'bg-transparent' : heatmapClass(value, item.data.max)"
                :aria-label="item.data.symmetric && valueIndex === rowIndex ? `Tổng Lead quan tâm ${row.label}: ${value}` : item.data.symmetric && valueIndex < rowIndex ? undefined : `${row.label} và ${item.data.labels[valueIndex]}: ${value ?? 'không áp dụng'} Lead`"
              >
                {{ item.data.symmetric && valueIndex < rowIndex ? '' : (value ?? '—') }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div
      v-else-if="item.type == 'data_table'"
      class="flex h-full w-full flex-col overflow-hidden rounded-md border border-outline-gray-1 bg-surface-white shadow-sm"
    >
      <div class="flex items-start justify-between gap-3 border-b px-4 py-3">
        <div>
          <div class="text-base font-medium text-ink-gray-9">
            {{ item.data.title }}
          </div>
          <div class="mt-0.5 text-xs text-ink-gray-5">
            {{ item.data.subtitle }}
          </div>
        </div>
        <Badge
          v-if="item.data.badge"
          variant="subtle"
          theme="gray"
          :label="item.data.badge"
        />
      </div>
      <div class="min-h-0 flex-1 overflow-auto">
        <table class="w-full border-collapse text-xs">
          <thead class="sticky top-0 bg-surface-gray-1 text-ink-gray-5">
            <tr>
              <th
                v-for="column in item.data.columns"
                :key="column.key"
                class="whitespace-nowrap border-b px-3 py-2 text-left font-medium"
              >
                {{ column.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, rowIndex) in item.data.rows"
              :key="rowIndex"
              class="hover:bg-surface-gray-1"
              :class="item.data.drilldown ? 'cursor-pointer' : ''"
              @click="item.data.drilldown && openLead(row)"
            >
              <td
                v-for="column in item.data.columns"
                :key="column.key"
                class="whitespace-nowrap border-b px-3 py-2 text-ink-gray-7"
              >
                <span :class="column.primary ? 'font-medium text-ink-gray-9' : ''">
                  {{ row[column.key] }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div
      v-else-if="item.type == 'signal_feed'"
      class="flex h-full w-full flex-col overflow-hidden rounded-md border border-outline-gray-1 bg-surface-white shadow-sm"
    >
      <div class="border-b px-4 py-3">
        <div class="text-base font-medium text-ink-gray-9">
          {{ item.data.title }}
        </div>
        <div class="mt-0.5 text-xs text-ink-gray-5">{{ item.data.subtitle }}</div>
      </div>
      <div class="min-h-0 flex-1 overflow-auto px-4">
        <div
          v-for="signal in item.data.signals"
          :key="`${signal.time}-${signal.lead}`"
          class="flex gap-3 border-b py-3 last:border-b-0"
        >
          <div class="mt-1 size-2 shrink-0 rounded-full bg-surface-gray-5"></div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-ink-gray-9">{{ signal.lead }}</span>
              <span class="text-xs text-ink-gray-5">{{ signal.time }}</span>
            </div>
            <div
              v-if="signal.ai_available === false"
              class="mt-1 text-xs leading-5 text-ink-gray-5"
              role="status"
            >
              {{ __('Phân tích AI tạm không khả dụng') }}
            </div>
            <div v-else class="mt-1 text-xs leading-5 text-ink-gray-6">
              {{ signal.message }}
            </div>
          </div>
        </div>
      </div>
    </div>
    <div
      v-else-if="item.type == 'status_panel'"
      class="flex h-full w-full items-center gap-3 overflow-x-auto rounded-md border border-outline-gray-1 bg-surface-white px-4 py-3 shadow-sm"
    >
      <div class="min-w-48 border-r pr-4">
        <div class="text-sm font-medium text-ink-gray-9">{{ item.data.title }}</div>
        <div class="mt-1 text-xs text-ink-gray-5">{{ item.data.subtitle }}</div>
      </div>
      <div
        v-for="metric in item.data.metrics"
        :key="metric.label"
        class="min-w-32 px-3"
      >
        <div class="text-xs text-ink-gray-5">{{ metric.label }}</div>
        <div class="mt-1 text-base font-semibold text-ink-gray-9">
          {{ metric.value }}
        </div>
      </div>
      <Button
        v-if="item.data.action"
        class="ml-auto shrink-0"
        :label="item.data.action"
        @click="$emit('refresh')"
      />
    </div>
  </div>
</template>
<script setup>
import { computed, defineComponent, h } from 'vue'
import { AxisChart, Badge, Button, DonutChart, NumberChart, Tooltip } from 'frappe-ui'
import { useRouter } from 'vue-router'

const props = defineProps({
  index: { type: Number, required: true },
  item: { type: Object, required: true },
  editing: { type: Boolean, default: false },
})

defineEmits(['refresh'])

const router = useRouter()

const axisChartConfig = computed(() => {
  if (!props.item?.data) return null
  const config = props.item.data
  const axisLabelDefaults = getAxisLabelDefaults(config)
  const tooltipFormatter = getDetailTooltipFormatter(config)
  return {
    ...config,
    xAxis: {
      ...config.xAxis,
      echartOptions: {
        ...config.xAxis?.echartOptions,
        axisLabel: {
          ...axisLabelDefaults,
          ...config.xAxis?.echartOptions?.axisLabel,
        },
      },
    },
    echartOptions: {
      ...config.echartOptions,
      xAxis: {
        ...config.echartOptions?.xAxis,
        axisLabel: {
          ...axisLabelDefaults,
          ...config.echartOptions?.xAxis?.axisLabel,
        },
      },
      ...(tooltipFormatter
        ? {
            tooltip: {
              ...config.echartOptions?.tooltip,
              formatter: tooltipFormatter,
            },
          }
        : {}),
    },
  }
})

function getAxisLabelDefaults(config) {
  if (config.xAxis?.type !== 'category' || !config.xAxis?.wrapLabels) {
    return { hideOverlap: true }
  }

  const labels = (config.data || []).map((row) => String(row?.[config.xAxis.key] || ''))
  const isDense = labels.length >= 6 || labels.some((label) => label.length > 12)

  if (!isDense) return { hideOverlap: true }

  return {
    hideOverlap: false,
    interval: 0,
    lineHeight: 14,
    margin: 10,
    formatter: formatCategoryAxisLabel,
  }
}

function formatCategoryAxisLabel(value) {
  const words = String(value).trim().split(/\s+/)
  const lines = []
  let line = ''

  for (const word of words) {
    const nextLine = line ? `${line} ${word}` : word
    if (nextLine.length > 12 && line) {
      lines.push(line)
      line = word
    } else {
      line = nextLine
    }
  }
  if (line) lines.push(line)

  return lines.length > 2 ? `${lines.slice(0, 2).join('\n')}…` : lines.join('\n')
}

function getDetailTooltipFormatter(config) {
  if (!config.data?.some((row) => row.province_detail)) return null

  return (params) => {
    const point = Array.isArray(params) ? params[0] : params
    const row = config.data[point?.dataIndex]
    if (!row) return ''

    const label = escapeHtml(row[config.xAxis.key])
    const detail = escapeHtml(row.province_detail)
    const value = escapeHtml(point?.value?.[1])

    return `<div class="flex flex-col gap-1"><b>${label}</b><span>${detail}</span><span>${point.marker} Verified Lead: <b>${value}</b></span></div>`
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character])
}

const Metric = defineComponent({
  props: { label: String, value: [String, Number], tone: String },
  setup: (props) => () =>
    h('div', [
      h('div', { class: 'text-ink-gray-5' }, props.label),
      h(
        'div',
        { class: `mt-0.5 font-medium ${props.tone || 'text-ink-gray-8'}` },
        props.value,
      ),
    ]),
})

const interestAccentMap = {
  amber: { bar: 'bg-amber-200', fill: 'bg-amber-500' },
  violet: { bar: 'bg-violet-200', fill: 'bg-violet-500' },
  teal: { bar: 'bg-teal-200', fill: 'bg-teal-500' },
  pink: { bar: 'bg-pink-200', fill: 'bg-pink-500' },
  cyan: { bar: 'bg-cyan-200', fill: 'bg-cyan-500' },
  blue: { bar: 'bg-blue-200', fill: 'bg-blue-500' },
  yellow: { bar: 'bg-yellow-200', fill: 'bg-yellow-500' },
  gray: { bar: 'bg-gray-200', fill: 'bg-gray-400' },
}

function interestAccent(color) {
  return interestAccentMap[color] || interestAccentMap.blue
}

function metricTone(label, value) {
  const text = String(value)
  if (text.startsWith('+')) return 'text-ink-green-2'
  if (text.startsWith('-')) return 'text-ink-red-3'
  if (label === 'Confidence thấp' || label === 'Quá SLA') return 'text-ink-amber-2'
  if (label === 'Đang tăng' || label === 'Chưa follow-up') return 'text-ink-blue-2'
  if (label === 'Đã có hồ sơ') return 'text-ink-green-2'
  return 'text-ink-gray-8'
}

function formatNumber(value) {
  return typeof value === 'number' ? value.toLocaleString('vi-VN') : value
}

function compactNumber(value) {
  return Intl.NumberFormat('vi-VN', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function sparkHeight(value, points) {
  const max = Math.max(...points)
  const min = Math.min(...points)
  return max === min ? 60 : 25 + ((value - min) / (max - min)) * 75
}

function readinessLevelClass(level) {
  return [
    'bg-blue-100',
    'bg-blue-200',
    'bg-blue-400',
    'bg-blue-500',
    'bg-blue-600',
  ][level]
}

function heatmapClass(value, max) {
  if (value == null) return 'bg-surface-gray-1 text-ink-gray-4'
  const ratio = value / max
  if (ratio >= 0.8) return 'bg-blue-500 text-ink-white'
  if (ratio >= 0.6) return 'bg-blue-400 text-ink-white'
  if (ratio >= 0.4) return 'bg-blue-300 text-ink-gray-9'
  if (ratio >= 0.2) return 'bg-blue-200 text-ink-gray-8'
  return 'bg-blue-100 text-ink-gray-7'
}

function openInterestLeads() {
  router.push({
    name: 'CRM Contacts',
    query: { interest_dimension: props.item.data.code },
  })
}

function openLead(row) {
  router.push({ name: 'CRM Contacts', query: { search: row.lead } })
}
</script>
