<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-white" :aria-label="title || __('Approvals')">
    <div class="border-b border-outline-gray-2 px-4 py-3"><h2 class="font-semibold text-ink-gray-9">{{ title || __('Approvals') }}</h2></div>
    <p v-if="!items.length" class="p-5 text-sm text-ink-gray-5">{{ emptyMessage || __('There are no approvals requiring your attention.') }}</p>
    <ul v-else class="divide-y divide-outline-gray-1"><li v-for="item in items" :key="item.id || item.name" class="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"><div><p class="font-medium text-ink-gray-8">{{ item.title || item.action || item.name }}</p><p v-if="item.description || item.reason" class="mt-1 text-sm text-ink-gray-6">{{ item.description || item.reason }}</p></div><div v-if="item.actions?.length" class="flex gap-2"><button v-for="action in item.actions" :key="action.key" class="rounded border border-outline-gray-3 px-3 py-1.5 text-sm focus:outline-none focus:ring-2" :disabled="busy === item.id" @click="decide(item, action)">{{ action.label }}</button></div></li></ul>
  </section>
</template>
<script setup>
import { ref } from 'vue'
const props = defineProps({ items: { type: Array, default: () => [] }, title: String, emptyMessage: String, onDecision: Function })
const emit = defineEmits(['decided', 'error'])
const busy = ref('')
async function decide(item, action) { if (!props.onDecision) return emit('decided', { item, action }); busy.value = item.id || item.name; try { await props.onDecision(item, action); emit('decided', { item, action }) } catch (error) { emit('error', error) } finally { busy.value = '' } }
</script>
