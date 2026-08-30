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
            {{
              __('The information most useful for the next admissions action.')
            }}
          </p>
        </div>
        <dl class="grid gap-4 sm:grid-cols-2">
          <div>
            <dt class="text-sm text-ink-gray-5">
              {{ __('Current assignment') }}
            </dt>
            <dd class="mt-1 truncate text-base text-ink-gray-8">
              <span
                v-if="ownershipLoading && !ownershipFetched"
                class="text-ink-gray-5"
                >{{ __('Loading…') }}</span
              >
              <span v-else>{{ ownershipSummary }}</span>
            </dd>
          </div>
          <div>
            <dt class="text-sm text-ink-gray-5">{{ __('Lifecycle') }}</dt>
            <dd class="mt-1 text-base font-medium text-ink-gray-8">
              <span
                v-if="engagementLoading && !engagementFetched"
                class="text-ink-gray-5"
              >
                {{ __('Loading…') }}
              </span>
              <span v-else>{{ lifecycleStage }}</span>
            </dd>
          </div>
          <div>
            <dt class="text-sm text-ink-gray-5">{{ __('Current grade') }}</dt>
            <dd class="mt-1 text-base text-ink-gray-8">
              <span
                v-if="engagementLoading && !engagementFetched"
                class="text-ink-gray-5"
              >
                {{ __('Loading…') }}
              </span>
              <span v-else>{{ currentGradeLabel }}</span>
            </dd>
          </div>
          <div>
            <dt class="text-sm text-ink-gray-5">{{ __('Study stage') }}</dt>
            <dd class="mt-1 text-base text-ink-gray-8">
              <span
                v-if="engagementLoading && !engagementFetched"
                class="text-ink-gray-5"
              >
                {{ __('Loading…') }}
              </span>
              <span v-else>{{ studyStageLabel }}</span>
            </dd>
          </div>
          <div v-if="geographyCurrentLabel">
            <dt class="text-sm text-ink-gray-5">{{ __('Current geography') }}</dt>
            <dd class="mt-1 text-base text-ink-gray-8">{{ geographyCurrentLabel }}</dd>
          </div>
        </dl>
      </section>

      <section
        v-if="assessmentCurrent || assessmentPending"
        class="rounded-lg border border-outline-gray-2 bg-surface-white p-4"
        aria-labelledby="student-overview-assessment"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2
              id="student-overview-assessment"
              class="text-base font-semibold text-ink-gray-9"
            >
              {{ __('Student 360 assessment') }}
            </h2>
            <p class="mt-1 text-sm text-ink-gray-5">
              {{ __('Explainable dimensions used to select the next action.') }}
            </p>
          </div>
          <Badge
            :label="assessmentCurrent?.status || __('Pending confirmation')"
            :theme="assessmentCurrent ? 'green' : 'orange'"
            variant="subtle"
          />
        </div>
        <dl v-if="assessmentCurrent" class="mt-4 grid gap-4 sm:grid-cols-3">
          <div>
            <dt class="text-sm text-ink-gray-5">{{ __('Interest') }}</dt>
            <dd class="mt-1 font-medium text-ink-gray-8">
              {{ assessmentCurrent.interest || __('Unknown') }}
            </dd>
          </div>
          <div>
            <dt class="text-sm text-ink-gray-5">{{ __('Fit') }}</dt>
            <dd class="mt-1 font-medium text-ink-gray-8">
              {{ assessmentCurrent.fit || __('Unknown') }}
            </dd>
          </div>
          <div>
            <dt class="text-sm text-ink-gray-5">{{ __('Primary barrier') }}</dt>
            <dd class="mt-1 font-medium text-ink-gray-8">
              {{ assessmentCurrent.primary_barrier || __('Unknown') }}
            </dd>
          </div>
        </dl>
        <p v-if="assessmentCurrent?.reason" class="mt-4 text-sm leading-6 text-ink-gray-6">
          <span class="font-medium text-ink-gray-8">{{ __('Why') }}:</span>
          {{ assessmentCurrent.reason }}
        </p>
        <p v-if="assessmentPending" class="mt-3 rounded bg-surface-gray-1 p-3 text-sm text-ink-orange-6">
          {{ __('A system assessment is waiting for staff confirmation before it can drive an action.') }}
        </p>
      </section>

      <section
        v-if="parentContext.length || privacyContext.status !== 'unknown' || privacyContext.requests?.length"
        class="rounded-lg border border-outline-gray-2 bg-surface-white p-4"
        aria-labelledby="student-overview-governance"
      >
        <h2 id="student-overview-governance" class="text-base font-semibold text-ink-gray-9">
          {{ __('Parent context and privacy') }}
        </h2>
        <div class="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <p v-if="parentContext.length" class="text-ink-gray-6">
            {{ __('Verified parent authorities: {0}', [parentContext.length]) }}
          </p>
          <p class="text-ink-gray-6">
            {{ __('Privacy status: {0}', [privacyContext.status || __('Unknown')]) }}
          </p>
          <p v-if="privacyContext.retention_until" class="text-ink-gray-6">
            {{ __('Retention until: {0}', [privacyContext.retention_until]) }}
          </p>
          <p v-if="privacyContext.requests?.length" class="text-ink-gray-6">
            {{ __('Privacy requests: {0}', [privacyContext.requests.length]) }}
          </p>
        </div>
      </section>

      <StudentAdmissionsContext
        :context="demoContext"
        :loading="demoContextLoading"
      />

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
          <p
            v-if="studentDecisionContext.pendingDecision"
            class="text-ink-gray-6"
          >
            {{
              __('Pending decision: {0}', [
                studentDecisionContext.pendingDecision.action ||
                  studentDecisionContext.pendingDecision.recommended_action ||
                  studentDecisionContext.pendingDecision.name,
              ])
            }}
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
              :class="
                studentDecisionContext.activeAction.overdue
                  ? 'font-medium text-red-600'
                  : 'text-ink-gray-6'
              "
            >
              {{
                __('Status: {0} · Due: {1}', [
                  studentDecisionContext.activeAction.status,
                  studentDecisionContext.activeAction.dueAt ||
                    __('Not scheduled'),
                ])
              }}
            </p>
            <Button
              v-if="
                studentDecisionContext.activeAction.permittedTransitions?.length
              "
              class="mt-2"
              size="sm"
              :label="__('Update action')"
              @click="
                relay('update-action', studentDecisionContext.activeAction)
              "
            />
          </div>
          <p
            v-if="studentDecisionContext.latestTerminalAction"
            class="text-ink-gray-6"
          >
            {{
              __('Latest action: {0}', [
                studentDecisionContext.latestTerminalAction.actionType,
              ])
            }}
            <span
              v-if="
                studentDecisionContext.latestTerminalAction.linkedInteraction
              "
            >
              ·
              {{
                __('Linked interaction: {0}', [
                  studentDecisionContext.latestTerminalAction.linkedInteraction,
                ])
              }}
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
            {{
              routingStatus.last_error_code ||
              __('Routing is operating normally.')
            }}
          </span>
          <Button
            v-if="
              ['deferred', 'failed'].includes(routingStatus.status) &&
              routingStatus.capabilities?.retry
            "
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
import { Badge } from 'frappe-ui'
import StudentSLASection from '@/components/StudentSLASection.vue'
import StudentAdmissionsContext from '@/components/StudentAdmissionsContext.vue'
import StudentConversionPanel from '@/components/StudentConversion/StudentConversionPanel.vue'
import AuditTimeline from '@/components/Governance/AuditTimeline.vue'
import { studentConversionState } from '@/utils/studentConversion'

const props = defineProps({
  student: { type: String, required: true },
  ownershipSummary: { type: String, default: '' },
  ownershipLoading: { type: Boolean, default: false },
  ownershipFetched: { type: Boolean, default: false },
  lifecycleStage: { type: String, default: '' },
  slaAttempt: { type: Object, default: null },
  slaCapabilities: { type: Object, default: () => ({}) },
  slaLoading: { type: Boolean, default: false },
  engagementContext: { type: Object, default: null },
  engagementLoading: { type: Boolean, default: false },
  engagementFetched: { type: Boolean, default: false },
  demoContext: { type: Object, default: null },
  demoContextLoading: { type: Boolean, default: false },
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

const CURRENT_GRADE_LABELS = {
  10: '10',
  11: '11',
  12: '12',
  post_exam: __('After final exam'),
}
const STUDY_STAGE_LABELS = {
  grade_10: __('Grade 10'),
  grade_11: __('Grade 11'),
  grade_12_h1: __('Grade 12 · Semester 1'),
  grade_12_h2: __('Grade 12 · Semester 2'),
  post_exam: __('After final exam'),
}
const currentGradeLabel = computed(
  () => CURRENT_GRADE_LABELS[props.engagementContext?.student?.current_grade] || __('Not specified'),
)
const studyStageLabel = computed(
  () => STUDY_STAGE_LABELS[props.engagementContext?.student?.study_stage] || __('Not specified'),
)
const assessmentCurrent = computed(
  () => props.engagementContext?.assessment?.current || null,
)
const assessmentPending = computed(
  () => props.engagementContext?.assessment?.pending || null,
)
const parentContext = computed(
  () => props.engagementContext?.parent_context || [],
)
const privacyContext = computed(
  () => props.engagementContext?.privacy || { status: 'unknown', requests: [] },
)
const geographyContext = computed(
  () => props.engagementContext?.geography || { current: null, history: [] },
)
const geographyCurrentLabel = computed(() => {
  const current = geographyContext.value.current || {}
  return [current.high_school, current.ward, current.province].filter(Boolean).join(' · ')
})

function relay(event, payload) {
  emit(event, payload)
}
</script>
