<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs :items="breadcrumbs">
        <template #prefix="{ item }">
          <Icon v-if="item.icon" :icon="item.icon" class="mr-2 h-4" />
        </template>
      </Breadcrumbs>
    </template>
    <template v-if="doc.name && !errorTitle" #right-header>
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
        :label="__('Admissions action')"
        iconLeft="plus"
        @click="showAdmissionsAction = true"
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
  <ErrorPage
    v-if="errorTitle"
    :errorTitle="errorTitle"
    :errorMessage="errorMessage"
  />
  <StudentDetailLoadingState v-else-if="isDocumentPending" />
  <div v-else-if="doc.name" class="flex h-full overflow-hidden">
    <Tabs
      v-model="tabIndex"
      :tabs="tabs"
      class="flex flex-1 overflow-hidden flex-col [&_[role='tab']]:px-0 [&_[role='tab']]:shrink-0 [&_[role='tablist']]:px-5 [&_[role='tablist']::-webkit-scrollbar]:h-0 [&_[role='tablist']]:min-h-[45px] [&_[role='tablist']]:gap-7.5 [&_[role='tabpanel']:not([hidden])]:flex [&_[role='tabpanel']:not([hidden])]:grow"
    >
      <template #tab-panel>
        <StudentOverview
          v-if="tabs[tabIndex]?.name === 'Overview'"
          :student="crmStudentId"
          :ownership-summary="ownershipSummary"
          :ownership-loading="ownership.loading"
          :ownership-fetched="ownership.fetched"
          :lifecycle-stage="lifecycleStage"
          :sla-attempt="studentSLA.data?.attempt"
          :sla-capabilities="studentSLA.data?.capabilities || {}"
          :sla-loading="studentSLA.loading"
          :engagement-context="engagementContext.data"
          :engagement-loading="engagementContext.loading"
          :engagement-fetched="engagementContext.fetched"
          :demo-context="studentDemoContext"
          :demo-context-loading="engagementContext.loading"
          :student-decision-context="studentDecisionContext"
          :routing-status="routingStatus.data"
          @sla-changed="handleSLAChanged"
          @sla-refresh-required="studentSLA.reload()"
          @update-action="selectedSalesAction = $event"
          @retry-routing="showRouteModal = true"
          @conversion-refresh-required="refreshConversionContext"
          @converted="handleConverted"
        />
        <Activities
          v-else-if="
            !['Interactions', 'Scoring'].includes(tabs[tabIndex]?.name)
          "
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
          :refresh-key="interactionRefreshKey"
          :can-record-outcome="Boolean(engagementContext.data)"
          @record-outcome="showOutcomeModal = true"
          @admissions-action="showAdmissionsAction = true"
        />
        <InteractionScoreArea
          v-else
          :student="doc"
          type="scores"
          :refresh-key="interactionRefreshKey"
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
      <div class="flex min-h-0 flex-1 flex-col overflow-hidden">
        <section class="border-b px-5 py-3" aria-label="Student summary">
          <div class="mb-3 text-sm font-semibold text-ink-gray-8">
            {{ __('At a glance') }}
          </div>
          <dl class="space-y-3 text-sm">
            <div class="flex items-center justify-between gap-3">
              <dt class="text-ink-gray-5">{{ __('Lifecycle') }}</dt>
              <dd class="truncate font-medium text-ink-gray-8">
                <span
                  v-if="engagementContext.loading && !engagementContext.data"
                  class="text-ink-gray-5"
                >
                  {{ __('Loading…') }}
                </span>
                <span v-else>{{ lifecycleStage }}</span>
              </dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-ink-gray-5">{{ __('Current assignment') }}</dt>
              <dd
                class="truncate text-right text-ink-gray-7"
                :title="ownershipSummary"
              >
                <span
                  v-if="ownership.loading && !ownership.data"
                  class="text-ink-gray-5"
                  >{{ __('Loading…') }}</span
                >
                <span v-else>{{ ownershipSummary }}</span>
              </dd>
            </div>
            <div
              v-if="studentSLA.data?.attempt"
              class="flex items-center justify-between gap-3"
            >
              <dt class="text-ink-gray-5">{{ __('SLA') }}</dt>
              <dd class="truncate text-right text-ink-gray-7">
                <Badge
                  :label="slaPresentation.label"
                  :theme="slaPresentation.theme"
                  variant="subtle"
                />
              </dd>
            </div>
            <div
              v-if="studentSLA.data?.attempt?.next_transition_at"
              class="flex items-center justify-between gap-3"
            >
              <dt class="text-ink-gray-5">{{ __('Next deadline') }}</dt>
              <dd class="truncate text-right text-ink-gray-7">
                {{
                  formatStudentSLADate(
                    studentSLA.data.attempt.next_transition_at,
                  )
                }}
              </dd>
            </div>
          </dl>
        </section>
        <StudentDetailLoadingState
          v-if="!hasSidePanelSections && !sections.error"
          class="min-h-0 flex-1 overflow-y-auto"
          variant="side-panel"
        />
        <div
          v-else-if="!hasSidePanelSections"
          class="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-5 text-center"
          role="alert"
        >
          <p class="text-sm text-ink-gray-6">
            {{ __('Unable to load student fields.') }}
          </p>
          <Button :label="__('Retry')" @click="sections.reload()" />
        </div>
        <SidePanelLayout
          v-else
          class="min-h-0 flex-1"
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
  <RecordStudentOutcomeModal
    v-if="showOutcomeModal && engagementContext.data"
    v-model="showOutcomeModal"
    :student="crmStudentId"
    :context="engagementContext.data"
    @changed="handleOutcomeChanged"
    @refresh-required="engagementContext.reload()"
  />
  <StudentAdmissionsActionDialog
    v-if="showAdmissionsAction"
    v-model="showAdmissionsAction"
    :student="crmStudentId"
    :expected-revision="engagementContext.data?.engagement_revision || 0"
    :actions="availableAdmissionsActions"
    @success="handleAdmissionsActionSuccess"
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
import DashboardIcon from '@/components/Icons/DashboardIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import NoteIcon from '@/components/Icons/NoteIcon.vue'
import AttachmentIcon from '@/components/Icons/AttachmentIcon.vue'
import SidePanelLayout from '@/components/SidePanelLayout.vue'
import CustomActions from '@/components/CustomActions.vue'
import InteractionScoreArea from '@/components/Activities/InteractionScoreArea.vue'
import ChangeStudentOwnershipModal from '@/components/Modals/ChangeStudentOwnershipModal.vue'
import RouteStudentModal from '@/components/Modals/RouteStudentModal.vue'
import StudentOverview from '@/components/StudentOverview.vue'
import TransitionStudentLifecycleModal from '@/components/Modals/TransitionStudentLifecycleModal.vue'
import RecordStudentOutcomeModal from '@/components/Modals/RecordStudentOutcomeModal.vue'
import SalesActionOutcomeDialog from '@/components/StudentDecision/SalesActionOutcomeDialog.vue'
import StudentAdmissionsActionDialog from '@/components/StudentAdmissionsActionDialog.vue'
import StudentDetailLoadingState from '@/components/StudentDetailLoadingState.vue'
import {
  lifecycleTargets,
  safeLifecycleError,
  studentEngagementApi,
} from '@/utils/studentEngagement'
import { salesActionItem } from '@/utils/studentDecision'
import { normalizeStudentAdmissionsContext } from '@/utils/studentAdmissionsContext'
import { formatStudentSLADate, slaStatusPresentation } from '@/utils/studentSLA'
import { copyToClipboard } from '@/utils'
import { usersStore } from '@/stores/users'
import { hasAnyCapability } from '@/utils/rolePolicy'
import { getSettings } from '@/stores/settings'
import { getMeta } from '@/stores/meta'
import { useDocument } from '@/data/document'
import {
  createResource,
  Tabs,
  Badge,
  Button,
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
const showAdmissionsAction = ref(false)
const interactionRefreshKey = ref(0)
const selectedSalesAction = ref(null)
const showSalesActionModal = computed({
  get: () => Boolean(selectedSalesAction.value),
  set: (value) => {
    if (!value) selectedSalesAction.value = null
  },
})
const canChangeOwnership = computed(() =>
  hasAnyCapability(getCurrentUser(), [
    'student.ownership.manage',
    'team.oversee',
    'admissions.oversee',
    'system.configure',
  ]),
)

const { document, error } = useDocument('CRM Student', props.crmStudentId)

const doc = computed(() => document.doc || {})
const isDocumentPending = computed(
  () =>
    !doc.value.name &&
    !errorTitle.value &&
    (!document.get?.fetched || Boolean(document.get?.loading)),
)

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
      data: {
        summary: event.summary || event.reason || __('Ownership changed'),
      },
    })),
)
const routingRequestId = computed(
  () =>
    ownership.data?.routing_request ||
    ownership.data?.latest_routing_request ||
    doc.value?.routing_request,
)
const studentSLA = createResource({
  url: 'crm.api.student_sla.get_student_sla_status',
  makeParams: () => ({ student: props.crmStudentId }),
  auto: true,
  initialData: null,
})
const slaPresentation = computed(() =>
  slaStatusPresentation(studentSLA.data?.attempt?.status),
)
const engagementContext = createResource({
  url: studentEngagementApi.getContext,
  makeParams: () => ({ student: props.crmStudentId, history_limit: 50 }),
  auto: true,
  initialData: null,
})
const lifecycleStage = computed(() => {
  const stage =
    engagementContext.data?.lifecycle?.current_stage ||
    engagementContext.data?.lifecycle?.stage ||
    doc.value?.enrollment_status
  return stage ? __(stage) : __('Lifecycle unavailable')
})
const canRequestLifecycleTransition = computed(
  () =>
    lifecycleTargets(engagementContext.data?.lifecycle).length > 0 &&
    engagementContext.data?.capabilities?.transition !== false,
)
const studentDecisionContext = computed(() => {
  // Phase 6 extends the existing Student context projection. Accept the
  // versioned section name while remaining harmless during a staged rollout.
  const context =
    engagementContext.data?.decision_context ||
    engagementContext.data?.decisions ||
    engagementContext.data?.phase_6 ||
    engagementContext.data?.decision
  if (!context) return null
  return {
    pendingDecision: context.pending_decision || context.pending_recommendation,
    activeAction: context.active_action
      ? salesActionItem(context.active_action)
      : null,
    latestTerminalAction: context.latest_terminal_action
      ? salesActionItem(context.latest_terminal_action)
      : null,
  }
})
const availableAdmissionsActions = computed(() => {
  const actions = engagementContext.data?.capabilities?.actions
  const admissionsActions =
    engagementContext.data?.admissions_context?.capabilities?.actions
  return Array.isArray(actions)
    ? actions
    : Array.isArray(admissionsActions)
      ? admissionsActions
      : []
})
const studentDemoContext = computed(() =>
  normalizeStudentAdmissionsContext(
    engagementContext.data?.admissions_context ||
      engagementContext.data?.demo_context,
    studentDecisionContext.value,
  ),
)
const engagementActivityEntries = computed(() => {
  const history =
    engagementContext.data?.history?.items ||
    engagementContext.data?.history ||
    []
  return history
    .filter((event) => event?.occurred_at || event?.creation)
    .map((event) => ({
      name: `student-engagement-${event.name || event.event_id || event.occurred_at}`,
      activity_type: 'student_engagement',
      creation: event.occurred_at || event.creation,
      data: {
        summary: event.to_stage
          ? __('Lifecycle changed to {0}', [__(event.to_stage)])
          : event.outcome
            ? __('Outcome recorded: {0}', [__(event.outcome)])
            : event.summary || __('Student lifecycle updated'),
      },
    }))
})
const engagementHistoryCursor = computed(
  () =>
    engagementContext.data?.history?.next_cursor ||
    engagementContext.data?.next_cursor,
)
const demoContextActivityEntries = computed(() =>
  studentDemoContext.value.activity.map((event) => ({
    name: `student-demo-context-${event.key}`,
    activity_type: 'student_engagement',
    creation: event.occurredAt,
    data: { summary: event.summary },
  })),
)
const studentActivityEntries = computed(() => [
  ...ownershipActivityEntries.value,
  ...engagementActivityEntries.value,
  ...demoContextActivityEntries.value,
])
const routingStatus = createResource({
  url: 'crm.api.student_routing.get_student_routing_status',
  makeParams: () => ({ request: routingRequestId.value }),
  auto: false,
  initialData: null,
})

watch(
  routingRequestId,
  (request) => {
    if (request) routingStatus.reload()
    else routingStatus.data = null
  },
  { immediate: true },
)

function handleOwnershipChanged(response) {
  ownership.reload()
  studentSLA.reload()
  if (response?.revision !== undefined)
    ownership.data = { ...ownership.data, ...response }
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
  document.reload?.()
}

function handleOutcomeChanged() {
  engagementContext.reload()
}

function handleAdmissionsActionSuccess() {
  interactionRefreshKey.value += 1
  reload.value = true
  document.reload?.()
  engagementContext.reload()
  ownership.reload()
  studentSLA.reload()
  toast.success(__('Admissions action saved.'))
}

function handleSalesActionChanged() {
  engagementContext.reload()
}

function refreshConversionContext() {
  engagementContext.reload()
  document.reload?.()
}

function handleConverted() {
  refreshConversionContext()
}

async function loadMoreEngagementHistory() {
  if (!engagementHistoryCursor.value) return
  try {
    const nextPage = await call(studentEngagementApi.getContext, {
      student: props.crmStudentId,
      history_cursor: engagementHistoryCursor.value,
      history_limit: 50,
    })
    const currentHistory =
      engagementContext.data?.history?.items ||
      engagementContext.data?.history ||
      []
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
    toast.error(
      safeLifecycleError(err, __('Unable to load more lifecycle history.')),
    )
  }
}

watch(error, (err) => {
  if (err) {
    errorTitle.value = __(
      err.exc_type == 'DoesNotExistError'
        ? 'Document not found'
        : 'Error occurred',
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
            doc.value?.enrollment_status === 'Đã chuyển đổi'
              ? 'enrolled'
              : 'intake',
        },
      },
    },
  ]
  items.push({
    label: doc.value?.student_name || props.crmStudentId,
    route: {
      name: 'CRM Student',
      params: { crmStudentId: props.crmStudentId },
    },
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
    onError: (err) =>
      toast.error(err.messages?.[0] || __('Error updating field')),
  })
}

const tabs = computed(() => [
  { name: 'Overview', label: __('Overview'), icon: DashboardIcon },
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
      columns:
        section.columns?.map((col) => ({
          ...col,
          fields:
            col.fields?.filter((f) => !hiddenFields.has(f.fieldname)) || [],
        })) || [],
    }))
  },
})
const hasSidePanelSections = computed(() => Array.isArray(sections.data))
</script>
