<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-white" :aria-label="title || __('Students')">
    <div class="flex items-center justify-between gap-3 border-b border-outline-gray-2 px-4 py-3">
      <h2 class="font-semibold text-ink-gray-9">{{ title || __('Students') }}</h2>
      <span v-if="stale" class="text-xs text-ink-amber-600" role="status">{{ __('Refreshing data') }}</span>
    </div>
    <div v-if="loading && !rows.length" class="p-5 text-sm text-ink-gray-5" role="status">{{ __('Loading work…') }}</div>
    <div v-else-if="!rows.length" class="p-5 text-sm text-ink-gray-5">{{ emptyMessage || __('No Students match this view.') }}</div>
    <template v-else>
      <div class="hidden overflow-x-auto md:block">
        <table class="w-full text-sm">
          <thead class="bg-surface-gray-1 text-left text-ink-gray-6"><tr><th v-for="column in columns" :key="column.key" class="px-4 py-3 font-medium">{{ __(column.label) }}</th><th class="px-4 py-3"><span class="sr-only">{{ __('Actions') }}</span></th></tr></thead>
          <tbody class="divide-y divide-outline-gray-1"><tr v-for="row in rows" :key="row.id || row.name" class="hover:bg-surface-gray-1"><td v-for="column in columns" :key="column.key" class="px-4 py-3 text-ink-gray-8">{{ row[column.key] ?? '—' }}</td><td class="px-4 py-3 text-right"><button class="text-sm font-medium text-ink-gray-8 underline focus:outline-none focus:ring-2" @click="$emit('open', row)">{{ __('Open') }}</button></td></tr></tbody>
        </table>
      </div>
      <div class="divide-y divide-outline-gray-1 md:hidden"><article v-for="row in rows" :key="row.id || row.name" class="p-4"><dl class="grid grid-cols-2 gap-x-4 gap-y-3"><template v-for="column in columns" :key="column.key"><dt class="text-xs text-ink-gray-5">{{ __(column.label) }}</dt><dd class="text-sm text-ink-gray-8">{{ row[column.key] ?? '—' }}</dd></template></dl><button class="mt-4 text-sm font-medium underline focus:outline-none focus:ring-2" @click="$emit('open', row)">{{ __('Open Student') }}</button></article></div>
      <div v-if="nextCursor" class="border-t border-outline-gray-1 p-3 text-center"><button class="rounded border border-outline-gray-3 px-3 py-1.5 text-sm focus:outline-none focus:ring-2" :disabled="loading" @click="$emit('load-more')">{{ loading ? __('Loading…') : __('Load more') }}</button></div>
    </template>
  </section>
</template>

<script setup>
defineProps({ rows: { type: Array, default: () => [] }, columns: { type: Array, default: () => [] }, title: String, loading: Boolean, stale: Boolean, nextCursor: String, emptyMessage: String })
defineEmits(['open', 'load-more'])
</script>
