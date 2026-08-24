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
        v-if="doc.name && doc.enrollment_status === 'Mới'"
        variant="solid"
        :label="__('Convert to Contact')"
        iconLeft="user-plus"
        :loading="converting"
        @click="convertToContact"
      />
      <Dropdown
        v-if="doc.enrollment_status"
        :options="enrollmentStatuses"
        placement="right"
      >
        <template #default="{ open }">
          <Button
            :label="doc.enrollment_status"
            :iconRight="open ? 'chevron-up' : 'chevron-down'"
          >
            <template #prefix>
              <IndicatorIcon :class="statusColor(doc.enrollment_status)" />
            </template>
          </Button>
        </template>
      </Dropdown>
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
          @afterSave="() => sections.reload()"
        />
        <InteractionScoreArea
          v-else-if="tabs[tabIndex]?.name === 'Interactions'"
          :student="doc"
          type="interactions"
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
        <section class="border-b px-5 py-4" aria-labelledby="ownership-heading">
          <div class="flex items-center justify-between gap-2">
            <h2 id="ownership-heading" class="text-sm font-medium text-ink-gray-8">{{ __('Ownership') }}</h2>
            <span v-if="ownership.loading" class="text-xs text-ink-gray-5" role="status">{{ __('Loading…') }}</span>
          </div>
          <p v-if="ownership.data" class="mt-1 text-sm text-ink-gray-6">
            {{ ownershipSummary }}
          </p>
          <p v-else class="mt-1 text-sm text-ink-gray-5">{{ __('Ownership details are unavailable.') }}</p>
          <ol v-if="ownershipEvents.length" class="mt-3 space-y-2 border-l pl-3 text-xs text-ink-gray-6" aria-label="Ownership history">
            <li v-for="event in ownershipEvents" :key="event.name || event.event_id || event.creation">
              <span class="font-medium text-ink-gray-7">{{ event.summary || event.reason || __('Ownership changed') }}</span>
              <span v-if="event.creation || event.timestamp"> · {{ event.creation || event.timestamp }}</span>
            </li>
          </ol>
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
</template>

<script setup>
import ErrorPage from '@/components/ErrorPage.vue'
import Icon from '@/components/Icon.vue'
import Resizer from '@/components/Resizer.vue'
import IndicatorIcon from '@/components/Icons/IndicatorIcon.vue'
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
import { copyToClipboard } from '@/utils'
import { usersStore } from '@/stores/users'
import { hasAnyCapability } from '@/utils/rolePolicy'
import { getSettings } from '@/stores/settings'
import { getMeta } from '@/stores/meta'
import { useDocument } from '@/data/document'
import {
  createResource,
  Dropdown,
  Tabs,
  Breadcrumbs,
  usePageMeta,
  toast,
} from 'frappe-ui'
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useActiveTabManager } from '@/composables/useActiveTabManager'

const { brand } = getSettings()
const { doctypeMeta } = getMeta('CRM Student')
const { getCurrentUser } = usersStore()

const route = useRoute()
const router = useRouter()

const props = defineProps({
  crmStudentId: { type: String, required: true },
})

const reload = ref(false)
const activities = ref(null)
const errorTitle = ref('')
const errorMessage = ref('')
const converting = ref(false)
const showOwnershipModal = ref(false)
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
const ownershipEvents = computed(() => ownership.data?.events || ownership.data?.history || [])

function handleOwnershipChanged(response) {
  ownership.reload()
  sections.reload()
  if (response?.revision !== undefined) ownership.data = { ...ownership.data, ...response }
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

const enrollmentStatusList = createResource({
  url: 'frappe.client.get_list',
  params: { doctype: 'CRM Enrollment Status', fields: ['name'], limit: 50, order_by: 'idx asc' },
  auto: true,
})

function statusColor() {
  return 'text-gray-500'
}

const enrollmentStatuses = computed(() =>
  (enrollmentStatusList.data || []).map((s) => ({
    label: s.name,
    onClick: () => updateStatus(s.name),
  })),
)

function updateStatus(status) {
  doc.value.enrollment_status = status
  document.save.submit(null, {
    onError: (err) => toast.error(err.messages?.[0] || __('Error updating status')),
  })
}

const convertResource = createResource({
  url: 'crm.fcrm.doctype.crm_student.crm_student.convert_to_contact',
  onSuccess(contactName) {
    converting.value = false
    toast.success(__('Converted to CRM Contact'))
    router.push({ name: 'CRM Contact', params: { crmContactId: contactName } })
  },
  onError(err) {
    converting.value = false
    toast.error(err.messages?.[0] || __('Conversion failed'))
  },
})

function convertToContact() {
  converting.value = true
  convertResource.submit({ student_name: props.crmStudentId })
}

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
