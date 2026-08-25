<template>
  <section class="border-b px-5 py-4" aria-labelledby="student-sla-heading">
    <div class="flex items-center justify-between gap-3">
      <h2 id="student-sla-heading" class="text-sm font-medium text-ink-gray-8">{{ __('Initial-response SLA') }}</h2>
      <span v-if="loading" class="text-xs text-ink-gray-5" role="status">{{ __('Loading…') }}</span>
    </div>
    <p v-if="!attempt && !loading" class="mt-1 text-sm text-ink-gray-5">{{ __('No active Student SLA attempt.') }}</p>
    <div v-else-if="attempt" class="mt-3 space-y-2 text-sm text-ink-gray-6">
      <div class="flex items-center justify-between gap-3">
        <span>{{ __('Status') }}</span>
        <Badge :label="presentation.label" :theme="presentation.theme" variant="subtle" />
      </div>
      <div class="flex items-center justify-between gap-3"><span>{{ __('Next deadline') }}</span><time :datetime="attempt.next_transition_at || undefined">{{ formatStudentSLADate(attempt.next_transition_at) }}</time></div>
      <div class="flex items-center justify-between gap-3"><span>{{ __('Breach deadline') }}</span><time :datetime="attempt.breach_at || undefined">{{ formatStudentSLADate(attempt.breach_at) }}</time></div>
      <div class="flex items-center justify-between gap-3"><span>{{ __('Paused') }}</span><span>{{ __('{0} min', [attempt.total_paused_minutes || 0]) }}</span></div>
      <div class="flex items-center justify-between gap-3"><span>{{ __('Policy version') }}</span><span>{{ attempt.sla_policy_version || __('Unavailable') }}</span></div>
      <div v-if="attempt.last_event" class="flex items-center justify-between gap-3"><span>{{ __('Last event') }}</span><span>{{ attempt.last_event }}</span></div>
    </div>
    <div v-if="attempt && canPause" class="mt-4 flex flex-wrap gap-2">
      <Button :label="attempt.status === 'paused' ? __('Resume SLA') : __('Pause SLA')" @click="showPauseModal = true" />
    </div>
  </section>
  <PauseStudentSLAModal
    v-if="showPauseModal && attempt"
    v-model="showPauseModal"
    :attempt="attempt"
    @changed="$emit('changed', $event)"
    @refresh-required="$emit('refresh-required')"
  />
</template>

<script setup>
import { Badge, Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import PauseStudentSLAModal from '@/components/Modals/PauseStudentSLAModal.vue'
import { formatStudentSLADate, slaStatusPresentation } from '@/utils/studentSLA'

defineEmits(['changed', 'refresh-required'])
const props = defineProps({
  attempt: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  capabilities: { type: Object, default: () => ({}) },
})
const showPauseModal = ref(false)
const presentation = computed(() => slaStatusPresentation(props.attempt?.status))
const canPause = computed(() => Boolean(props.capabilities?.pause))
</script>
