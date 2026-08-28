<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-white" :aria-label="title || __('Organization')">
    <header class="border-b border-outline-gray-2 px-4 py-3"><h2 class="font-semibold text-ink-gray-9">{{ title || __('Organization') }}</h2><p v-if="description" class="mt-1 text-sm text-ink-gray-6">{{ description }}</p></header>
    <p v-if="!items.length" class="p-5 text-sm text-ink-gray-5" role="status">{{ emptyMessage || __('No organization data is available for this view.') }}</p>
    <template v-else>
      <div class="hidden overflow-x-auto md:block"><table class="w-full text-sm"><thead class="bg-surface-gray-1 text-left text-ink-gray-6"><tr><th class="px-4 py-3 font-medium">{{ __('Name') }}</th><th class="px-4 py-3 font-medium">{{ __('Type') }}</th><th class="px-4 py-3 font-medium">{{ __('Membership') }}</th><th class="px-4 py-3 font-medium">{{ __('Effective scope') }}</th><th class="px-4 py-3"><span class="sr-only">{{ __('Manage') }}</span></th></tr></thead><tbody class="divide-y divide-outline-gray-1"><tr v-for="item in items" :key="itemKey(item)"><td class="px-4 py-3 font-medium text-ink-gray-8">{{ item.name || item.label || '—' }}</td><td class="px-4 py-3 text-ink-gray-7">{{ item.type || '—' }}</td><td class="px-4 py-3 tabular-nums text-ink-gray-7">{{ membershipLabel(item) }}</td><td class="px-4 py-3 text-ink-gray-7">{{ item.scopeSummary || '—' }}</td><td class="px-4 py-3 text-right"><DelegatedLink :item="item" /></td></tr></tbody></table></div>
      <div class="divide-y divide-outline-gray-1 md:hidden"><article v-for="item in items" :key="itemKey(item)" class="p-4"><h3 class="font-medium text-ink-gray-8">{{ item.name || item.label || '—' }}</h3><dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-3"><div><dt class="text-xs text-ink-gray-5">{{ __('Type') }}</dt><dd class="mt-1 text-sm text-ink-gray-7">{{ item.type || '—' }}</dd></div><div><dt class="text-xs text-ink-gray-5">{{ __('Membership') }}</dt><dd class="mt-1 text-sm text-ink-gray-7">{{ membershipLabel(item) }}</dd></div><div class="col-span-2"><dt class="text-xs text-ink-gray-5">{{ __('Effective scope') }}</dt><dd class="mt-1 text-sm text-ink-gray-7">{{ item.scopeSummary || '—' }}</dd></div></dl><div v-if="item.manageUrl" class="mt-4"><DelegatedLink :item="item" /></div></article></div>
    </template>
  </section>
</template>

<script>
export function organizationMembershipLabel(item = {}) {
  const count = item.memberCount ?? item.membershipCount
  return Number.isFinite(count) ? String(count) : '—'
}
</script>

<script setup>
import { computed, defineComponent, h } from 'vue'
import { safeInternalUrl } from '@/utils/safeInternalUrl'
defineProps({ title: String, description: String, items: { type: Array, default: () => [] }, emptyMessage: String })
const DelegatedLink = defineComponent({
  props: { item: { type: Object, required: true } },
  setup(linkProps) {
    const label = computed(() => linkProps.item.manageLabel || __('Open approved settings'))
    const href = computed(() => safeInternalUrl(linkProps.item.manageUrl))
    return () => href.value ? h('a', { href: href.value, target: '_blank', rel: 'noopener noreferrer', class: 'text-sm font-medium text-ink-gray-8 underline focus:outline-none focus:ring-2 focus:ring-outline-gray-5' }, label.value) : null
  },
})
function itemKey(item) { return item.id || item.key || item.name || item.label }
function membershipLabel(item) { return organizationMembershipLabel(item) }
</script>
