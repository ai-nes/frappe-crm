<template>
  <section
    v-if="items.length"
    class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
    :aria-label="__('Workspace summary')"
  >
    <component
      :is="item.drilldown ? 'button' : 'article'"
      v-for="item in items"
      :key="item.key || item.label"
      class="group relative flex flex-col justify-between rounded-xl border border-outline-gray-2/80 bg-surface-white p-4.5 text-left shadow-xs transition-all duration-150"
      :class="
        item.drilldown
          ? 'cursor-pointer hover:border-outline-gray-3 hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-outline-gray-4'
          : ''
      "
      :type="item.drilldown ? 'button' : undefined"
      @click="item.drilldown && $emit('drilldown', item)"
    >
      <div>
        <div class="flex items-center justify-between gap-2">
          <p class="truncate text-xs font-semibold uppercase tracking-wider text-ink-gray-5">
            {{ __(item.label) }}
          </p>
          <div class="flex items-center gap-1 text-ink-gray-4">
            <span
              v-if="item.definition"
              class="cursor-help transition hover:text-ink-gray-6"
              :title="item.definition"
              aria-label="Definition"
            >
              <FeatherIcon name="info" class="size-3.5" />
            </span>
            <span
              v-if="item.drilldown"
              class="transition group-hover:text-ink-gray-8"
            >
              <FeatherIcon name="arrow-up-right" class="size-3.5" />
            </span>
          </div>
        </div>

        <p class="mt-2 text-2xl sm:text-3xl font-bold tracking-tight tabular-nums text-ink-gray-9">
          {{ displayValue(item) }}
        </p>
      </div>

      <div class="mt-3 space-y-1.5">
        <p v-if="item.comparison" class="text-xs text-ink-gray-6">
          {{ item.comparison }}
        </p>

        <div
          v-if="item.nullReason || item.availability === 'suppressed'"
          class="flex items-center gap-1.5 rounded-md border border-amber-200/60 bg-amber-50/80 px-2 py-1 text-xs text-amber-900"
          role="status"
        >
          <FeatherIcon name="shield" class="size-3 shrink-0 text-amber-600" />
          <span class="truncate">{{ nullStateMessage(item) }}</span>
        </div>

        <div
          v-if="item.coverage || item.scopeLabel"
          class="flex items-center gap-1 text-xs text-ink-gray-5"
        >
          <FeatherIcon name="map-pin" class="size-3 shrink-0 text-ink-gray-4" />
          <span>{{ item.coverage || item.scopeLabel }}</span>
        </div>
      </div>
    </component>
  </section>
</template>

<script setup>
import { FeatherIcon } from 'frappe-ui'

defineProps({ items: { type: Array, default: () => [] } })
defineEmits(['drilldown'])

function displayValue(item) {
  if (item.value == null) return '—'
  if (typeof item.value === 'number')
    return (
      new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(
        item.value,
      ) + (item.unit === 'percent' ? '%' : '')
    )
  return String(item.value)
}

function nullStateMessage(item) {
  const messages = {
    privacy_suppressed: __('Dữ liệu được ẩn để bảo vệ riêng tư.'),
    insufficient_forecast_data: __('Chưa đủ dữ liệu lịch sử để đưa ra dự báo.'),
  }
  return messages[item.nullReason] || __('Chưa có dữ liệu cho chỉ số này.')
}
</script>
