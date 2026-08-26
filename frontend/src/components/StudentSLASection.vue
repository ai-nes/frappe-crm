<template>
  <section class="border-b p-1 sm:p-3" aria-label="Initial-response SLA">
    <Section
      :label="__('Initial-response SLA')"
      label-class="px-2 font-semibold"
      header-class="h-8"
    >
      <template #actions>
        <span v-if="loading" class="mr-2 text-xs text-ink-gray-5" role="status">{{ __('Loading…') }}</span>
      </template>
      <div class="px-3">
        <p v-if="!attempt && !loading" class="mt-3 text-sm text-ink-gray-5">{{ __('No active Student SLA attempt.') }}</p>
        <div v-else-if="attempt" class="mt-3 space-y-2 text-sm text-ink-gray-6">
          <div class="flex items-center justify-between gap-3">
            <span>{{ __('Status') }}</span>
            <Badge :label="presentation.label" :theme="presentation.theme" variant="subtle" />
          </div>
          <div class="flex items-center justify-between gap-3"><span>{{ __('Next deadline') }}</span><time :datetime="attempt.next_transition_at || undefined">{{ formatStudentSLADate(attempt.next_transition_at) }}</time></div>
          <div class="flex items-center justify-between gap-3"><span>{{ __('Breach deadline') }}</span><time :datetime="attempt.breach_at || undefined">{{ formatStudentSLADate(attempt.breach_at) }}</time></div>
          <div class="flex items-center justify-between gap-3"><span>{{ __('Paused') }}</span><span>{{ __('{0} min', [attempt.total_paused_minutes || 0]) }}</span></div>
          <div class="flex items-center justify-between gap-3"><span>{{ __('Policy version') }}</span><span>{{ attempt.sla_policy_version || __('Unavailable') }}</span></div>
        </div>
        <div v-if="attempt && canPause" class="mt-4 flex flex-wrap gap-2">
          <Button :label="attempt.status === 'paused' ? __('Resume SLA') : __('Pause SLA')" @click="showPauseModal = true" />
        </div>
      </div>
    </Section>
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
import Section from '@/components/Section.vue'
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
