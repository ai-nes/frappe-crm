<template>
  <section v-if="resource.data?.read_enabled !== false" class="border-b p-1 sm:p-3" aria-label="Student case history">
    <Section :label="__('Student case history')" label-class="px-2 font-semibold" header-class="h-8">
      <div class="space-y-3 px-3 pb-3 text-sm">
        <p v-if="resource.loading && !history.items.length" class="text-ink-gray-5" role="status">{{ __('Loading conversion history…') }}</p>
        <p v-else-if="loadError" class="text-red-600" role="alert">{{ loadError }}</p>
        <template v-else>
          <ol v-if="history.items.length" class="divide-y" aria-label="Converted Student cases">
            <li v-for="item in history.items" :key="item.name || `${item.label}-${item.convertedAt}`" class="py-2">
              <p class="font-medium text-ink-gray-8">{{ item.label }}</p>
              <p v-if="item.convertedAt" class="text-xs text-ink-gray-5">{{ formatDate(item.convertedAt) }}</p>
            </li>
          </ol>
          <p v-else class="text-ink-gray-5">{{ __('No visible Student conversion history is available.') }}</p>
          <p v-if="history.redactedCount" class="text-xs text-ink-gray-5">{{ __('Some Student cases are restricted by your access.') }}</p>
          <Button v-if="history.nextCursor" size="sm" :label="__('Load more')" :loading="loadingMore" :disabled="loadingMore" @click="loadMore" />
        </template>
      </div>
    </Section>
  </section>
</template>

<script setup>
import Section from '@/components/Section.vue'
import { contactConversionHistory, safeConversionError, studentConversionApi } from '@/utils/studentConversion'
import { Button, call, createResource } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({ contact: { type: String, required: true } })
const loadingMore = ref(false)
const appended = ref([])
const resource = createResource({
  url: studentConversionApi.getContactHistory,
  makeParams: () => ({ contact: props.contact, limit: 20 }),
  auto: true,
  initialData: null,
})
const baseHistory = computed(() => contactConversionHistory(resource.data || {}))
const history = computed(() => ({ ...baseHistory.value, items: [...appended.value, ...baseHistory.value.items] }))
const loadError = computed(() => resource.error ? safeConversionError(resource.error, __('Unable to load conversion history.')) : '')

function formatDate(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

async function loadMore() {
  if (!baseHistory.value.nextCursor || loadingMore.value) return
  loadingMore.value = true
  try {
    const page = contactConversionHistory(await call(studentConversionApi.getContactHistory, {
      contact: props.contact, limit: 20, cursor: baseHistory.value.nextCursor,
    }))
    appended.value = [...history.value.items, ...page.items]
    resource.data = { history: { items: [], next_cursor: page.nextCursor, redacted_count: page.redactedCount } }
  } finally {
    loadingMore.value = false
  }
}
</script>
