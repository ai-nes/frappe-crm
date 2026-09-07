<template>
  <section
    v-if="overview"
    class="mt-3 rounded-md border border-outline-gray-2 bg-surface-white p-3 text-xs text-ink-gray-8"
    data-testid="overview-360-card"
  >
    <div class="mb-2 flex items-center justify-between">
      <h3 class="font-semibold text-ink-gray-9">
        {{ overview.subject_type === 'student' ? __('Student 360') : __('School 360') }}
      </h3>
      <span class="text-ink-gray-5">{{ overview.subject_id }}</span>
    </div>
    <p class="mb-3 text-sm text-ink-gray-8">{{ overview.summary }}</p>
    <template v-for="section in sections" :key="section.key">
      <div v-if="section.items.length" class="mb-2">
        <div class="mb-1 font-medium text-ink-gray-7">{{ section.label }}</div>
        <ul class="space-y-1">
          <li v-for="item in section.items" :key="`${section.key}-${item.title}-${item.detail}`">
            <span class="font-medium">{{ item.title }}:</span> {{ item.detail }}
          </li>
        </ul>
      </div>
    </template>
    <div v-if="Array.isArray(overview.data_quality) && overview.data_quality.length" class="mt-2 border-t border-outline-gray-2 pt-2 text-ink-gray-5">
      {{ __('Data quality') }}: {{ overview.data_quality.join(', ') }}
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  overview: {
    type: Object,
    default: null,
  },
})

const sections = computed(() => [
  { key: 'signals', label: __('Signals'), items: Array.isArray(props.overview?.signals) ? props.overview.signals : [] },
  { key: 'risks', label: __('Risks'), items: Array.isArray(props.overview?.risks) ? props.overview.risks : [] },
  { key: 'opportunities', label: __('Opportunities'), items: Array.isArray(props.overview?.opportunities) ? props.overview.opportunities : [] },
  { key: 'recent_changes', label: __('Recent changes'), items: Array.isArray(props.overview?.recent_changes) ? props.overview.recent_changes : [] },
])
</script>
