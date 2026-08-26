<template>
  <div class="h-full overflow-y-auto">
    <div class="mx-auto flex max-w-5xl flex-col gap-4 p-3 sm:p-6">
      <section
        class="rounded-lg border border-outline-gray-2 bg-surface-white p-4"
        aria-labelledby="student-overview-current-state"
      >
        <div class="mb-4">
          <h2
            id="student-overview-current-state"
            class="text-base font-semibold text-ink-gray-9"
          >
            {{ __('Current state') }}
          </h2>
          <p class="mt-1 text-sm text-ink-gray-5">
            {{ __('The information most useful for the next admissions action.') }}
          </p>
        </div>
        <dl class="grid gap-4 sm:grid-cols-2">
          <div>
            <dt class="text-sm text-ink-gray-5">{{ __('Current assignment') }}</dt>
            <dd class="mt-1 truncate text-base text-ink-gray-8">
              <span v-if="ownershipLoading" class="text-ink-gray-5">{{ __('Loading…') }}</span>
              <span v-else>{{ ownershipSummary }}</span>
            </dd>
          </div>
          <div>
            <dt class="text-sm text-ink-gray-5">{{ __('Lifecycle') }}</dt>
            <dd class="mt-1 text-base font-medium text-ink-gray-8">
              {{ lifecycleStage }}
            </dd>
          </div>
        </dl>
      </section>

      <StudentSLASection
        v-if="slaAttempt || slaLoading"
        class="rounded-lg border border-outline-gray-2 bg-surface-white"
        :attempt="slaAttempt"
        :capabilities="slaCapabilities"
        :loading="slaLoading"
        @changed="relay('sla-changed', $event)"
        @refresh-required="relay('sla-refresh-required')"
      />

      <section
        v-if="hasSalesDecision"
        class="rounded-lg border border-outline-gray-2 bg-surface-white p-4"
        aria-labelledby="student-overview-sales-actions"
      >
        <h2
          id="student-overview-sales-actions"
          class="text-base font-semibold text-ink-gray-9"
        >
          {{ __('Sales decisions and actions') }}
        </h2>
        <div class="mt-3 space-y-3 text-sm">
          <p v-if="studentDecisionContext.pendingDecision" class="text-ink-gray-6">
            {{ __('Pending decision: {0}', [studentDecisionContext.pendingDecision.action || studentDecisionContext.pendingDecision.recommended_action || studentDecisionContext.pendingDecision.name]) }}
          </p>
          <div
            v-if="studentDecisionContext.activeAction"
            class="rounded bg-surface-gray-1 p-3"
          >
            <p class="font-medium text-ink-gray-8">
              {{ studentDecisionContext.activeAction.actionType }}
            </p>
            <p
              class="mt-1"
              :class="studentDecisionContext.activeAction.overdue ? 'font-medium text-red-600' : 'text-ink-gray-6'"
            >
              {{ __('Status: {0} · Due: {1}', [studentDecisionContext.activeAction.status, studentDecisionContext.activeAction.dueAt || __('Not scheduled')]) }}
            </p>
            <Button
              v-if="studentDecisionContext.activeAction.permittedTransitions?.length"
              class="mt-2"
              size="sm"
              :label="__('Update action')"
              @click="relay('update-action', studentDecisionContext.activeAction)"
            />
          </div>
          <p v-if="studentDecisionContext.latestTerminalAction" class="text-ink-gray-6">
            {{ __('Latest action: {0}', [studentDecisionContext.latestTerminalAction.actionType]) }}
            <span v-if="studentDecisionContext.latestTerminalAction.linkedInteraction">
              · {{ __('Linked interaction: {0}', [studentDecisionContext.latestTerminalAction.linkedInteraction]) }}
            </span>
          </p>
        </div>
      </section>

      <section
        v-if="routingStatus?.status"
        class="rounded-lg border border-outline-gray-2 bg-surface-white p-4"
        aria-labelledby="student-overview-routing"
      >
        <div class="flex items-center justify-between gap-3">
          <h2
            id="student-overview-routing"
            class="text-base font-semibold text-ink-gray-9"
          >
            {{ __('Student routing') }}
          </h2>
          <span class="text-sm text-ink-gray-6">
            {{ __(routingStatus.status) }}
          </span>
        </div>
        <div class="mt-3 flex items-center justify-between gap-3 text-sm">
          <span class="text-ink-gray-6">
            {{ routingStatus.last_error_code || __('Routing is operating normally.') }}
          </span>
          <Button
            v-if="['deferred', 'failed'].includes(routingStatus.status) && routingStatus.capabilities?.retry"
            size="sm"
            :label="__('Retry')"
            @click="relay('retry-routing')"
          />
        </div>
      </section>

      <StudentConversionPanel
        v-if="showConversion"
        class="rounded-lg border border-outline-gray-2 bg-surface-white"
        :student="student"
        :context="engagementContext"
        :loading="engagementLoading"
        @refresh-required="relay('conversion-refresh-required')"
        @converted="relay('converted', $event)"
      />

      <AuditTimeline :student="student" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Button } from 'frappe-ui'
import StudentSLASection from '@/components/StudentSLASection.vue'
import StudentConversionPanel from '@/components/StudentConversion/StudentConversionPanel.vue'
import AuditTimeline from '@/components/Governance/AuditTimeline.vue'
import { studentConversionState } from '@/utils/studentConversion'

const props = defineProps({
  student: { type: String, required: true },
  ownershipSummary: { type: String, default: '' },
  ownershipLoading: { type: Boolean, default: false },
  lifecycleStage: { type: String, default: '' },
  slaAttempt: { type: Object, default: null },
  slaCapabilities: { type: Object, default: () => ({}) },
  slaLoading: { type: Boolean, default: false },
  engagementContext: { type: Object, default: null },
  engagementLoading: { type: Boolean, default: false },
  studentDecisionContext: { type: Object, default: null },
  routingStatus: { type: Object, default: null },
})

const emit = defineEmits([
  'sla-changed',
  'sla-refresh-required',
  'update-action',
  'retry-routing',
  'conversion-refresh-required',
  'converted',
])

const hasSalesDecision = computed(() => {
  const decision = props.studentDecisionContext
  return Boolean(
    decision?.pendingDecision ||
    decision?.activeAction ||
    decision?.latestTerminalAction,
  )
})

const showConversion = computed(() => {
  const state = studentConversionState(props.engagementContext || {})
  return state.advertised || state.converted
})

function relay(event, payload) {
  emit(event, payload)
}
</script>
