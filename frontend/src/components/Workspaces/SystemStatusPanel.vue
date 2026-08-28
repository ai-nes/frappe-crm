<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-white" :aria-label="title || __('System status')">
    <header class="border-b border-outline-gray-2 px-4 py-3">
      <h2 class="font-semibold text-ink-gray-9">{{ title || __('System status') }}</h2>
      <p v-if="description" class="mt-1 text-sm text-ink-gray-6">{{ description }}</p>
    </header>

    <p v-if="!items.length" class="p-5 text-sm text-ink-gray-5" role="status">
      {{ emptyMessage || __('No system status is available for this view.') }}
    </p>

    <template v-else>
      <div class="hidden overflow-x-auto md:block">
        <table class="w-full text-sm">
          <thead class="bg-surface-gray-1 text-left text-ink-gray-6">
            <tr>
              <th class="px-4 py-3 font-medium">{{ __('Service') }}</th>
              <th class="px-4 py-3 font-medium">{{ __('Status') }}</th>
              <th class="px-4 py-3 font-medium">{{ __('Account / endpoint') }}</th>
              <th class="px-4 py-3 font-medium">{{ __('Owner') }}</th>
              <th class="px-4 py-3 font-medium">{{ __('Last activity') }}</th>
              <th class="px-4 py-3 font-medium"><span class="sr-only">{{ __('Runbook') }}</span></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-outline-gray-1">
            <tr v-for="item in items" :key="itemKey(item)">
              <td class="px-4 py-3 font-medium text-ink-gray-8">{{ item.label || item.name || '—' }}</td>
              <td class="px-4 py-3"><StatusBadge :state="item.state" /></td>
              <td class="px-4 py-3 text-ink-gray-7">{{ displayIdentity(item) }}</td>
              <td class="px-4 py-3 text-ink-gray-7">{{ item.owner || '—' }}</td>
              <td class="px-4 py-3 text-ink-gray-7">{{ activitySummary(item) }}</td>
              <td class="px-4 py-3 text-right"><RunbookLink :item="item" /></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="divide-y divide-outline-gray-1 md:hidden">
        <article v-for="item in items" :key="itemKey(item)" class="p-4">
          <div class="flex items-start justify-between gap-3"><h3 class="font-medium text-ink-gray-8">{{ item.label || item.name || '—' }}</h3><StatusBadge :state="item.state" /></div>
          <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
            <div><dt class="text-xs text-ink-gray-5">{{ __('Account / endpoint') }}</dt><dd class="mt-1 break-all text-sm text-ink-gray-7">{{ displayIdentity(item) }}</dd></div>
            <div><dt class="text-xs text-ink-gray-5">{{ __('Owner') }}</dt><dd class="mt-1 text-sm text-ink-gray-7">{{ item.owner || '—' }}</dd></div>
            <div class="col-span-2"><dt class="text-xs text-ink-gray-5">{{ __('Last activity') }}</dt><dd class="mt-1 text-sm text-ink-gray-7">{{ activitySummary(item) }}</dd></div>
          </dl>
          <div v-if="item.runbookUrl" class="mt-4"><RunbookLink :item="item" /></div>
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
import { safeInternalUrl } from '@/utils/safeInternalUrl'

defineProps({
  title: String,
  description: String,
  items: { type: Array, default: () => [] },
  emptyMessage: String,
})

const statusClasses = {
  ready: 'bg-surface-green-2 text-ink-green-3',
  degraded: 'bg-surface-amber-2 text-ink-amber-3',
  not_configured: 'bg-surface-gray-2 text-ink-gray-6',
  unavailable: 'bg-surface-red-2 text-ink-red-3',
}

const StatusBadge = defineComponent({
  props: { state: String },
  setup(badgeProps) {
    return () => h('span', { class: ['inline-flex rounded px-2 py-1 text-xs font-medium', statusClasses[normalizedStatus(badgeProps.state)]] }, statusLabel(badgeProps.state))
  },
})

const RunbookLink = defineComponent({
  props: { item: { type: Object, required: true } },
  setup(linkProps) {
    const label = computed(() => linkProps.item.runbookLabel || __('Open runbook'))
    const href = computed(() => safeInternalUrl(linkProps.item.runbookUrl))
    return () => href.value
      ? h('a', { href: href.value, target: '_blank', rel: 'noopener noreferrer', class: 'text-sm font-medium text-ink-gray-8 underline focus:outline-none focus:ring-2 focus:ring-outline-gray-5' }, label.value)
      : null
  },
})

function itemKey(item) { return item.id || item.key || item.name || item.label }
function displayIdentity(item) { return displayStatusIdentity(item) }
function activitySummary(item) { return systemActivitySummary(item) }
</script>
