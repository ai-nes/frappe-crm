<template>
  <section
    class="rounded-xl border border-outline-gray-2/80 bg-surface-white shadow-xs overflow-hidden"
    :aria-label="title || __('Trạng thái hệ thống')"
  >
    <header class="border-b border-outline-gray-1 px-5 py-3.5">
      <h2 class="text-sm font-semibold text-ink-gray-9">
        {{ title || __('Trạng thái hệ thống') }}
      </h2>
      <p v-if="description" class="mt-0.5 text-xs text-ink-gray-6">
        {{ description }}
      </p>
    </header>

    <div
      v-if="!items.length"
      class="flex flex-col items-center justify-center py-12 text-center text-sm text-ink-gray-5"
      role="status"
    >
      <FeatherIcon name="activity" class="size-8 text-ink-gray-4 mb-2 opacity-50" />
      <p>{{ emptyMessage || __('Chưa có trạng thái hệ thống cho chế độ xem này.') }}</p>
    </div>

    <template v-else>
      <div class="hidden overflow-x-auto md:block">
        <table class="w-full text-xs sm:text-sm">
          <thead class="bg-surface-gray-2 text-left text-ink-gray-6 font-semibold uppercase tracking-wider text-[11px]">
            <tr>
              <th class="px-4 py-3">{{ __('Dịch vụ') }}</th>
              <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
              <th class="px-4 py-3">{{ __('Tài khoản / Điểm cuối') }}</th>
              <th class="px-4 py-3">{{ __('Người phụ trách') }}</th>
              <th class="px-4 py-3">{{ __('Hoạt động gần nhất') }}</th>
              <th class="px-4 py-3 text-right">
                <span class="sr-only">{{ __('Hướng dẫn vận hành') }}</span>
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-outline-gray-1">
            <tr
              v-for="item in items"
              :key="itemKey(item)"
              class="transition-colors hover:bg-surface-gray-1/60"
            >
              <td class="px-4 py-3 font-medium text-ink-gray-9">
                {{ item.label || item.name || '—' }}
              </td>
              <td class="px-4 py-3"><StatusBadge :state="item.state" /></td>
              <td class="px-4 py-3 font-mono text-xs text-ink-gray-7">
                {{ displayIdentity(item) }}
              </td>
              <td class="px-4 py-3 text-ink-gray-7">{{ item.owner || '—' }}</td>
              <td class="px-4 py-3 text-ink-gray-7">{{ activitySummary(item) }}</td>
              <td class="px-4 py-3 text-right"><RunbookLink :item="item" /></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="divide-y divide-outline-gray-1 md:hidden">
        <article
          v-for="item in items"
          :key="itemKey(item)"
          class="p-4 transition-colors hover:bg-surface-gray-1/40"
        >
          <div class="flex items-start justify-between gap-3">
            <h3 class="font-medium text-ink-gray-9">
              {{ item.label || item.name || '—' }}
            </h3>
            <StatusBadge :state="item.state" />
          </div>
          <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5">
            <div>
              <dt class="text-xs text-ink-gray-5">{{ __('Tài khoản / Điểm cuối') }}</dt>
              <dd class="mt-0.5 break-all font-mono text-xs text-ink-gray-8">
                {{ displayIdentity(item) }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-ink-gray-5">{{ __('Người phụ trách') }}</dt>
              <dd class="mt-0.5 text-sm text-ink-gray-8">{{ item.owner || '—' }}</dd>
            </div>
            <div class="col-span-2">
              <dt class="text-xs text-ink-gray-5">{{ __('Hoạt động gần nhất') }}</dt>
              <dd class="mt-0.5 text-sm text-ink-gray-8">{{ activitySummary(item) }}</dd>
            </div>
          </dl>
          <div v-if="item.runbookUrl" class="mt-3">
            <RunbookLink :item="item" />
          </div>
        </article>
      </div>
    </template>
  </section>
</template>

<script>
export function normalizedStatus(state) {
  return ['ready', 'degraded', 'not_configured', 'unavailable'].includes(state)
    ? state
    : 'unavailable'
}

export function maskCredential(value) {
  const text = String(value || '').trim()
  if (!text) return '—'
  if (text.length <= 4) return '••••'
  return `${text.slice(0, 2)}••••${text.slice(-2)}`
}

export function statusLabel(state) {
  return {
    ready: __('Available'),
    degraded: __('Needs attention'),
    not_configured: __('Not configured'),
    unavailable: __('Unavailable'),
  }[normalizedStatus(state)]
}

export function displayStatusIdentity(item = {}) {
  return maskCredential(item.maskedIdentity || item.account || item.endpoint)
}

export function systemActivitySummary(item = {}) {
  if (item.lastFailureAt) return __('Last failure: {0}', [item.lastFailureAt])
  if (item.lastSuccessAt) return __('Last success: {0}', [item.lastSuccessAt])
  return item.message || '—'
}
</script>

<script setup>
import { computed, defineComponent, h } from 'vue'
import { FeatherIcon } from 'frappe-ui'
import { safeInternalUrl } from '@/utils/safeInternalUrl'

defineProps({
  title: String,
  description: String,
  items: { type: Array, default: () => [] },
  emptyMessage: String,
})

const statusThemes = {
  ready: 'bg-green-50 text-green-700 border border-green-200/60',
  degraded: 'bg-amber-50 text-amber-800 border border-amber-200/60',
  not_configured: 'bg-surface-gray-2 text-ink-gray-6 border border-outline-gray-2',
  unavailable: 'bg-red-50 text-red-700 border border-red-200/60',
}

const StatusBadge = defineComponent({
  props: { state: String },
  setup(badgeProps) {
    return () =>
      h(
        'span',
        {
          class: [
            'inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium',
            statusThemes[normalizedStatus(badgeProps.state)],
          ],
        },
        statusLabel(badgeProps.state),
      )
  },
})

const RunbookLink = defineComponent({
  props: { item: { type: Object, required: true } },
  setup(linkProps) {
    const label = computed(() => linkProps.item.runbookLabel || __('Mở runbook'))
    const href = computed(() => safeInternalUrl(linkProps.item.runbookUrl))
    return () =>
      href.value
        ? h(
            'a',
            {
              href: href.value,
              target: '_blank',
              rel: 'noopener noreferrer',
              class:
                'inline-flex items-center gap-1 text-xs font-medium text-ink-gray-8 hover:text-ink-gray-9 underline focus:outline-none focus:ring-2 focus:ring-outline-gray-4',
            },
            label.value,
          )
        : null
  },
})

function itemKey(item) {
  return item.id || item.key || item.name || item.label
}
function displayIdentity(item) {
  return displayStatusIdentity(item)
}
function activitySummary(item) {
  return systemActivitySummary(item)
}
</script>
