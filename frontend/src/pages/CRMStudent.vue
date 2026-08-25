<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="breadcrumbs">
        <template #prefix="{ item }">
          <Icon v-if="item.icon" :icon="item.icon" class="mr-2 h-4" />
        </template>
      </Breadcrumbs>
    </template>
    <template v-if="!errorTitle" #right-header>
      <CustomActions
        v-if="document._actions?.length"
        :actions="document._actions"
      />
      <Button
        v-if="canChangeOwnership"
        :label="__('Change ownership')"
        iconLeft="users"
        @click="showOwnershipModal = true"
      />
      <Button
        v-if="doc.enrollment_status"
        :label="lifecycleStage"
        iconLeft="shuffle"
        :disabled="!canRequestLifecycleTransition"
        @click="showLifecycleModal = true"
      />
    </template>
  </LayoutHeader>
  <div v-if="doc.name" class="flex h-full overflow-hidden">
    <Tabs
      v-model="tabIndex"
      :tabs="tabs"
      class="flex flex-1 overflow-hidden flex-col [&_[role='tab']]:px-0 [&_[role='tab']]:shrink-0 [&_[role='tablist']]:px-5 [&_[role='tablist']::-webkit-scrollbar]:h-0 [&_[role='tablist']]:min-h-[45px] [&_[role='tablist']]:gap-7.5 [&_[role='tabpanel']:not([hidden])]:flex [&_[role='tabpanel']:not([hidden])]:grow"
    >
      <template #tab-panel>
        <Activities
          v-if="!['Interactions', 'Scoring'].includes(tabs[tabIndex]?.name)"
          ref="activities"
          v-model:reload="reload"
          v-model:tabIndex="tabIndex"
          doctype="CRM Student"
          :docname="crmStudentId"
          :tabs="tabs"
          :additional-activities="studentActivityEntries"
          :additional-activities-has-more="Boolean(engagementHistoryCursor)"
          @afterSave="() => sections.reload()"
          @load-more-additional-activities="loadMoreEngagementHistory"
        />
        <InteractionScoreArea
          v-else-if="tabs[tabIndex]?.name === 'Interactions'"
          :student="doc"
          type="interactions"
          :can-record-outcome="Boolean(engagementContext.data)"
          @record-outcome="showOutcomeModal = true"
        />
        <InteractionScoreArea
          v-else
          :student="doc"
          type="scores"
        />
      </template>
    </Tabs>
    <Resizer class="flex flex-col justify-between border-l" side="right">
      <div
        class="flex h-[45px] cursor-copy items-center border-b px-5 py-2.5 text-lg font-medium text-ink-gray-9"
        @click="copyToClipboard(crmStudentId)"
      >
        {{ __(doc.student_name || crmStudentId) }}
      </div>
      <div
        v-if="sections.data"
        class="flex flex-1 flex-col justify-between overflow-hidden"
      >
        <section class="border-b p-1 sm:p-3" aria-label="Ownership">
          <Section
            :label="__('Ownership')"
            label-class="px-2 font-semibold"
            header-class="h-8"
          >
            <template #actions>
              <span v-if="ownership.loading" class="mr-2 text-xs text-ink-gray-5" role="status">{{ __('Loading…') }}</span>
            </template>
            <div class="px-3">
              <p v-if="ownership.data" class="mt-3 text-sm text-ink-gray-6">
                {{ ownershipSummary }}
              </p>
              <p v-else class="mt-3 text-sm text-ink-gray-5">{{ __('Ownership details are unavailable.') }}</p>
            </div>
          </Section>
        </section>
        <StudentSLASection
          :attempt="studentSLA.data?.attempt"
          :capabilities="studentSLA.data?.capabilities || {}"
          :loading="studentSLA.loading"
          @changed="handleSLAChanged"
          @refresh-required="studentSLA.reload()"
        />
        <StudentEngagementSection
          :context="engagementContext.data"
          :loading="engagementContext.loading"
          :error="engagementContextError"
        />
        <StudentConversionPanel
          :student="crmStudentId"
          :context="engagementContext.data"
          :loading="engagementContext.loading"
          @refresh-required="refreshConversionContext"
          @converted="handleConverted"
        />
        <section class="border-b p-1 sm:p-3" aria-label="Sales decisions and actions">
          <Section
            :label="__('Sales decisions and actions')"
            label-class="px-2 font-semibold"
            header-class="h-8"
          >
            <div class="space-y-2 px-3 pb-3 text-sm">
              <p v-if="engagementContext.loading" class="text-ink-gray-5" role="status">{{ __('Loading decision context…') }}</p>
              <template v-else-if="studentDecisionContext">
                <p v-if="studentDecisionContext.pendingDecision" class="text-ink-gray-6">{{ __('Pending decision: {0}', [studentDecisionContext.pendingDecision.action || studentDecisionContext.pendingDecision.recommended_action || studentDecisionContext.pendingDecision.name]) }}</p>
                <div v-if="studentDecisionContext.activeAction" class="rounded bg-surface-gray-1 p-2">
                  <p class="font-medium text-ink-gray-8">{{ studentDecisionContext.activeAction.actionType }}</p>
                  <p class="mt-1" :class="studentDecisionContext.activeAction.overdue ? 'font-medium text-red-600' : 'text-ink-gray-6'">{{ __('Status: {0} · Due: {1}', [studentDecisionContext.activeAction.status, studentDecisionContext.activeAction.dueAt || __('Not scheduled')]) }}</p>
                  <Button v-if="studentDecisionContext.activeAction.permittedTransitions.length" class="mt-2" size="sm" :label="__('Update action')" @click="selectedSalesAction = studentDecisionContext.activeAction" />
                </div>
                <p v-if="studentDecisionContext.latestTerminalAction" class="text-ink-gray-6">{{ __('Latest action: {0}', [studentDecisionContext.latestTerminalAction.actionType]) }}<span v-if="studentDecisionContext.latestTerminalAction.linkedInteraction"> · {{ __('Linked interaction: {0}', [studentDecisionContext.latestTerminalAction.linkedInteraction]) }}</span></p>
                <p v-if="!studentDecisionContext.pendingDecision && !studentDecisionContext.activeAction && !studentDecisionContext.latestTerminalAction" class="text-ink-gray-5">{{ __('No current decision or Sales Action.') }}</p>
              </template>
              <p v-else class="text-ink-gray-5">{{ __('Decision context is unavailable.') }}</p>
            </div>
          </Section>
        </section>
        <section v-if="routingStatus.data" class="border-b px-5 py-3" aria-label="Student routing">
          <div class="flex items-center justify-between gap-3 text-sm">
            <span class="font-semibold text-ink-gray-8">{{ __('Student routing') }}</span>
            <div class="flex min-w-0 items-center gap-2">
              <span class="truncate text-ink-gray-6" :title="routingStatus.data.last_error_code || undefined">
                {{ __('Status: {0}', [routingStatus.data.status]) }}
              </span>
              <Button
                v-if="['deferred', 'failed'].includes(routingStatus.data.status) && routingStatus.data.capabilities?.retry"
                size="sm"
                :label="__('Retry')"
                @click="showRouteModal = true"
              />
            </div>
          </div>
        </section>
        <SidePanelLayout
          :sections="sections.data"
          doctype="CRM Student"
          :docname="crmStudentId"
          @reload="sections.reload"
          @beforeFieldChange="handleSidePanelFieldChange"
          @afterFieldChange="() => sections.reload()"
        />
      </div>
    </Resizer>
  </div>
  <ErrorPage
    v-else-if="errorTitle"
    :errorTitle="errorTitle"
    :errorMessage="errorMessage"
  />
  <ChangeStudentOwnershipModal
    v-if="showOwnershipModal"
    v-model="showOwnershipModal"
    :student="crmStudentId"
    :ownership="ownership.data || {}"
    @changed="handleOwnershipChanged"
    @refresh-required="ownership.reload()"
  />
  <RouteStudentModal
    v-if="showRouteModal && routingStatus.data"
    v-model="showRouteModal"
    :routing="routingStatus.data"
    @changed="handleRoutingChanged"
    @refresh-required="routingStatus.reload()"
  />
  <TransitionStudentLifecycleModal
    v-if="showLifecycleModal && engagementContext.data"
    v-model="showLifecycleModal"
    :student="crmStudentId"
    :lifecycle="engagementContext.data.lifecycle || {}"
    @changed="handleLifecycleChanged"
          @refresh-required="engagementContext.reload()"
        />
        <AuditTimeline :student="crmStudentId" />
  <RecordStudentOutcomeModal
    v-if="showOutcomeModal && engagementContext.data"
    v-model="showOutcomeModal"
    :student="crmStudentId"
    :context="engagementContext.data"
    @changed="handleOutcomeChanged"
    @refresh-required="engagementContext.reload()"
  />
  <SalesActionOutcomeDialog
    v-if="selectedSalesAction"
    v-model="showSalesActionModal"
    :action="selectedSalesAction"
    @changed="handleSalesActionChanged"
    @refresh-required="engagementContext.reload()"
  />
</template>

<script setup>
import ErrorPage from '@/components/ErrorPage.vue'
import Icon from '@/components/Icon.vue'
import Resizer from '@/components/Resizer.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import Activities from '@/components/Activities/Activities.vue'
import ActivityIcon from '@/components/Icons/ActivityIcon.vue'
import DetailsIcon from '@/components/Icons/DetailsIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import NoteIcon from '@/components/Icons/NoteIcon.vue'
import AttachmentIcon from '@/components/Icons/AttachmentIcon.vue'
import SidePanelLayout from '@/components/SidePanelLayout.vue'
import CustomActions from '@/components/CustomActions.vue'
import InteractionScoreArea from '@/components/Activities/InteractionScoreArea.vue'
import ChangeStudentOwnershipModal from '@/components/Modals/ChangeStudentOwnershipModal.vue'
import RouteStudentModal from '@/components/Modals/RouteStudentModal.vue'
import StudentSLASection from '@/components/StudentSLASection.vue'
import StudentEngagementSection from '@/components/StudentEngagementSection.vue'
import AuditTimeline from '@/components/Governance/AuditTimeline.vue'
import StudentConversionPanel from '@/components/StudentConversion/StudentConversionPanel.vue'
import Section from '@/components/Section.vue'
import TransitionStudentLifecycleModal from '@/components/Modals/TransitionStudentLifecycleModal.vue'
import RecordStudentOutcomeModal from '@/components/Modals/RecordStudentOutcomeModal.vue'
import SalesActionOutcomeDialog from '@/components/StudentDecision/SalesActionOutcomeDialog.vue'
import { lifecycleTargets, safeLifecycleError, studentEngagementApi } from '@/utils/studentEngagement'
import { salesActionItem } from '@/utils/studentDecision'
import { copyToClipboard } from '@/utils'
import { usersStore } from '@/stores/users'
import { hasAnyCapability } from '@/utils/rolePolicy'
import { getSettings } from '@/stores/settings'
import { getMeta } from '@/stores/meta'
import { useDocument } from '@/data/document'
import {
  createResource,
  Tabs,
  Breadcrumbs,
  usePageMeta,
  toast,
  call,
} from 'frappe-ui'
import { ref, computed, watch } from 'vue'
import { useActiveTabManager } from '@/composables/useActiveTabManager'

const { brand } = getSettings()
const { doctypeMeta } = getMeta('CRM Student')
const { getCurrentUser } = usersStore()

const props = defineProps({
  crmStudentId: { type: String, required: true },
})

const reload = ref(false)
const activities = ref(null)
const errorTitle = ref('')
const errorMessage = ref('')
const showOwnershipModal = ref(false)
const showRouteModal = ref(false)
const showLifecycleModal = ref(false)
const showOutcomeModal = ref(false)
const selectedSalesAction = ref(null)
const showSalesActionModal = computed({
  get: () => Boolean(selectedSalesAction.value),
  set: (value) => { if (!value) selectedSalesAction.value = null },
})
const canChangeOwnership = computed(() =>
  hasAnyCapability(getCurrentUser(), [
    'student.execute',
    'team.oversee',
    'admissions.oversee',
    'system.configure',
  ]),
)

const { document, error } = useDocument(
  'CRM Student',
  props.crmStudentId,
)

const doc = computed(() => document.doc || {})

const ownership = createResource({
  url: 'crm.api.student_ownership.get_student_ownership',
  makeParams: () => ({ student: props.crmStudentId }),
  auto: true,
  initialData: null,
})
const ownershipSummary = computed(() => {
  const state = ownership.data || {}
  const owner = state.owner_staff_label || state.owner_staff
  const pool = state.owning_team_label || state.owning_team
  const target = owner || pool
  if (!target) return __('No active owner or pool.')
  return owner
    ? __('Owner: {0} · Revision {1}', [owner, state.revision ?? 0])
    : __('Pool: {0} · Revision {1}', [pool, state.revision ?? 0])
})
const ownershipActivityEntries = computed(() =>
  (ownership.data?.events || ownership.data?.history || [])
    .filter((event) => event?.creation || event?.timestamp)
    .map((event) => ({
      name: `student-ownership-${event.name || event.event_id || event.creation || event.timestamp}`,
      activity_type: 'student_engagement',
      creation: event.creation || event.timestamp,
      data: { summary: event.summary || event.reason || __('Ownership changed') },
    })),
)
const routingRequestId = computed(() =>
  ownership.data?.routing_request || ownership.data?.latest_routing_request || doc.value?.routing_request,
)
const studentSLA = createResource({
  url: 'crm.api.student_sla.get_student_sla_status',
  makeParams: () => ({ student: props.crmStudentId }),
  auto: true,
  initialData: null,
})
const engagementContext = createResource({
  url: studentEngagementApi.getContext,
  makeParams: () => ({ student: props.crmStudentId, history_limit: 50 }),
  auto: true,
  initialData: null,
})
const lifecycleStage = computed(() =>
  engagementContext.data?.lifecycle?.current_stage ||
  engagementContext.data?.lifecycle?.stage ||
  doc.value?.enrollment_status ||
  __('Lifecycle unavailable'),
)
const canRequestLifecycleTransition = computed(() =>
  lifecycleTargets(engagementContext.data?.lifecycle).length > 0 &&
  engagementContext.data?.capabilities?.transition !== false,
)
const engagementContextError = computed(() =>
  engagementContext.error ? safeLifecycleError(engagementContext.error, __('Unable to load engagement context.')) : '',
)
const studentDecisionContext = computed(() => {
  // Phase 6 extends the existing Student context projection. Accept the
  // versioned section name while remaining harmless during a staged rollout.
  const context = engagementContext.data?.decision_context || engagementContext.data?.decisions || engagementContext.data?.phase_6 || engagementContext.data?.decision
  if (!context) return null
  return {
    pendingDecision: context.pending_decision || context.pending_recommendation,
    activeAction: context.active_action ? salesActionItem(context.active_action) : null,
    latestTerminalAction: context.latest_terminal_action ? salesActionItem(context.latest_terminal_action) : null,
  }
})
const engagementActivityEntries = computed(() => {
  const history = engagementContext.data?.history?.items || engagementContext.data?.history || []
  return history
    .filter((event) => event?.occurred_at || event?.creation)
    .map((event) => ({
      name: `student-engagement-${event.name || event.event_id || event.occurred_at}`,
      activity_type: 'student_engagement',
      creation: event.occurred_at || event.creation,
      data: {
        summary: event.to_stage
          ? __('Lifecycle changed to {0}', [event.to_stage])
          : event.outcome
            ? __('Outcome recorded: {0}', [event.outcome])
            : event.summary || __('Student lifecycle updated'),
      },
    }))
})
const engagementHistoryCursor = computed(() =>
  engagementContext.data?.history?.next_cursor || engagementContext.data?.next_cursor,
)
const studentActivityEntries = computed(() => [
  ...ownershipActivityEntries.value,
  ...engagementActivityEntries.value,
])
const routingStatus = createResource({
  url: 'crm.api.student_routing.get_student_routing_status',
  makeParams: () => ({ request: routingRequestId.value }),
  auto: false,
  initialData: null,
})

watch(routingRequestId, (request) => {
  if (request) routingStatus.reload()
  else routingStatus.data = null
}, { immediate: true })

function handleOwnershipChanged(response) {
  ownership.reload()
  sections.reload()
  studentSLA.reload()
  if (response?.revision !== undefined) ownership.data = { ...ownership.data, ...response }
}

function handleSLAChanged(response) {
  studentSLA.data = { ...studentSLA.data, attempt: response }
  studentSLA.reload()
}

function handleRoutingChanged() {
  routingStatus.reload()
  ownership.reload()
  studentSLA.reload()
}

function handleLifecycleChanged() {
  engagementContext.reload()
  sections.reload()
  document.reload?.()
}

function handleOutcomeChanged() {
  engagementContext.reload()
  sections.reload()
}

function handleSalesActionChanged() {
  engagementContext.reload()
  sections.reload()
}

function refreshConversionContext() {
  engagementContext.reload()
  document.reload?.()
}

function handleConverted() {
  refreshConversionContext()
  sections.reload()
}

async function loadMoreEngagementHistory() {
  if (!engagementHistoryCursor.value) return
  try {
    const nextPage = await call(studentEngagementApi.getContext, {
      student: props.crmStudentId,
      history_cursor: engagementHistoryCursor.value,
      history_limit: 50,
    })
    const currentHistory = engagementContext.data?.history?.items || engagementContext.data?.history || []
    const nextHistory = nextPage?.history?.items || nextPage?.history || []
    engagementContext.data = {
      ...engagementContext.data,
      ...nextPage,
      history: {
        ...(nextPage?.history || {}),
        items: [...currentHistory, ...nextHistory],
      },
    }
  } catch (err) {
    toast.error(safeLifecycleError(err, __('Unable to load more lifecycle history.')))
  }
}

watch(error, (err) => {
  if (err) {
    errorTitle.value = __(
      err.exc_type == 'DoesNotExistError' ? 'Document not found' : 'Error occurred',
    )
    errorMessage.value = __(err.messages?.[0] || 'An error occurred')
  } else {
    errorTitle.value = ''
    errorMessage.value = ''
  }
})

const breadcrumbs = computed(() => {
  let items = [
    {
      label:
        doc.value?.enrollment_status === 'Đã chuyển đổi'
          ? __('Enrolled Students')
          : __('Prospective Students'),
      route: {
        name: 'CRM Students',
        query: {
          stage:
            doc.value?.enrollment_status === 'Đã chuyển đổi' ? 'enrolled' : 'intake',
        },
      },
    },
  ]
  items.push({
    label: doc.value?.student_name || props.crmStudentId,
    route: { name: 'CRM Student', params: { crmStudentId: props.crmStudentId } },
  })
  return items
})

const title = computed(() => {
  let t = doctypeMeta.value?.title_field || 'name'
  return doc.value?.[t] || props.crmStudentId
})

usePageMeta(() => ({ title: title.value, icon: brand.favicon }))

function handleSidePanelFieldChange() {
  document.save.submit(null, {
    onSuccess: () => sections.reload(),
    onError: (err) => toast.error(err.messages?.[0] || __('Error updating field')),
  })
}

const tabs = computed(() => [
  { name: 'Data', label: __('Data'), icon: DetailsIcon },
  { name: 'Activity', label: __('Activity'), icon: ActivityIcon },
  { name: 'Interactions', label: __('Interactions'), icon: ActivityIcon },
  { name: 'Scoring', label: __('Potential Score'), icon: ActivityIcon },
  { name: 'Tasks', label: __('Tasks'), icon: TaskIcon },
  { name: 'Notes', label: __('Notes'), icon: NoteIcon },
  { name: 'Attachments', label: __('Attachments'), icon: AttachmentIcon },
])

const { tabIndex } = useActiveTabManager(tabs, 'lastCRMStudentTab')

const sections = createResource({
  url: 'crm.fcrm.doctype.fields_layout.fields_layout.get_sidepanel_sections',
  cache: ['sidePanelSections', 'CRM Student'],
  params: { doctype: 'CRM Student' },
  auto: true,
  transform: (data) => {
    const hiddenFields = new Set([
      'converted',
      'latest_score',
      'assigned_to',
      'owner_staff',
      'owning_team',
      'section_assignment_history',
      'assignment_log',
      'enrollment_status',
      'lifecycle_stage',
    ])
    return data.map((section) => ({
      ...section,
      columns: section.columns?.map((col) => ({
        ...col,
        fields: col.fields?.filter((f) => !hiddenFields.has(f.fieldname)) || [],
      })) || [],
    }))
  },
})
</script>
