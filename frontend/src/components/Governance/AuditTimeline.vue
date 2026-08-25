<template>
  <section v-if="resource.data?.read_enabled !== false" class="border-b p-1 sm:p-3" aria-label="Critical admission history">
    <Section :label="__('Critical admission history')" label-class="px-2 font-semibold" header-class="h-8">
      <div class="space-y-3 px-3 pb-3 text-sm">
        <p v-if="resource.loading && !timeline.items.length" class="text-ink-gray-5" role="status">{{ __('Loading admission history…') }}</p>
        <div v-else-if="resource.error" role="alert" class="space-y-2 text-ink-red-3">
          <p>{{ errorState.message }}</p>
          <Button v-if="errorState.retryable" size="sm" :label="__('Retry')" @click="resource.reload()" />
        </div>
        <template v-else>
          <p v-if="timeline.completeness && timeline.completeness.complete === false" class="rounded bg-surface-amber-1 px-3 py-2 text-ink-amber-4" role="status">
            {{ __('Some history sources are temporarily unavailable.') }}
          </p>
          <ol v-if="timeline.items.length" class="divide-y" aria-label="Critical admission events">
            <li v-for="item in timeline.items" :key="item.id || `${item.eventType}-${item.occurredAt}`" class="py-3">
              <p class="font-medium text-ink-gray-8">{{ item.eventType }}</p>
              <p class="text-xs text-ink-gray-5">{{ formatDate(item.occurredAt) }} · {{ item.actor }}</p>
              <p v-if="item.transition" class="mt-1 text-ink-gray-6">{{ item.transition }}</p>
              <p v-if="item.reason" class="mt-1 text-ink-gray-6">{{ item.reason }}</p>
            </li>
          </ol>
          <p v-else class="text-ink-gray-5">{{ __('No visible critical admission history is available.') }}</p>
          <Button v-if="timeline.nextCursor" size="sm" :label="__('Load more')" :loading="loadingMore" :disabled="loadingMore" @click="loadMore" />
        </template>
      </div>
    </Section>
  </section>
</template>

<script setup>
import Section from '@/components/Section.vue'
import { governanceAuditApi, governanceErrorState, normalizeTimeline } from '@/utils/governanceAudit'
import { Button, call, createResource } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({ student: { type: String, required: true } })
const loadingMore = ref(false)
const appended = ref([])
const resource = createResource({
  url: governanceAuditApi.getTimeline,
  makeParams: () => ({ student: props.student, limit: 20 }),
  auto: true,
  initialData: null,
})
const page = computed(() => normalizeTimeline(resource.data || {}))
const timeline = computed(() => ({ ...page.value, items: [...appended.value, ...page.value.items] }))
const errorState = computed(() => governanceErrorState(resource.error))

function formatDate(value) {
  if (!value) return __('Time unavailable')
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

async function loadMore() {
  if (!page.value.nextCursor || loadingMore.value) return
  loadingMore.value = true
  try {
    const next = normalizeTimeline(await call(governanceAuditApi.getTimeline, { student: props.student, limit: 20, cursor: page.value.nextCursor }))
    appended.value = [...timeline.value.items, ...next.items]
    resource.data = { items: [], next_cursor: next.nextCursor, completeness: next.completeness }
  } finally {
    loadingMore.value = false
  }
}
</script>
