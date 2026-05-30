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
          ref="activities"
          v-model:reload="reload"
          v-model:tabIndex="tabIndex"
          doctype="Enrollment Student"
          :docname="enrollmentStudentId"
          :tabs="tabs"
          @afterSave="() => sections.reload()"
        />
      </template>
    </Tabs>
    <Resizer class="flex flex-col justify-between border-l" side="right">
      <div
        class="flex h-[45px] cursor-copy items-center border-b px-5 py-2.5 text-lg font-medium text-ink-gray-9"
        @click="copyToClipboard(enrollmentStudentId)"
      >
        {{ __(doc.student_name || enrollmentStudentId) }}
      </div>
      <div
        v-if="sections.data"
        class="flex flex-1 flex-col justify-between overflow-hidden"
      >
        <SidePanelLayout
          :sections="sections.data"
          doctype="Enrollment Student"
          :docname="enrollmentStudentId"
          @reload="sections.reload"
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
import { copyToClipboard } from '@/utils'
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
import { useRoute } from 'vue-router'
import { useActiveTabManager } from '@/composables/useActiveTabManager'

const { brand } = getSettings()
const { doctypeMeta } = getMeta('Enrollment Student')

const route = useRoute()

const props = defineProps({
  enrollmentStudentId: { type: String, required: true },
})

const reload = ref(false)
const activities = ref(null)
const errorTitle = ref('')
const errorMessage = ref('')

const { document, error } = useDocument('Enrollment Student', props.enrollmentStudentId)

const doc = computed(() => document.doc || {})

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
  let items = [{ label: __('Enrollment Students'), route: { name: 'Enrollment Students' } }]
  items.push({
    label: doc.value?.student_name || props.enrollmentStudentId,
    route: { name: 'Enrollment Student', params: { enrollmentStudentId: props.enrollmentStudentId } },
  })
  return items
})

const title = computed(() => {
  let t = doctypeMeta.value?.title_field || 'name'
  return doc.value?.[t] || props.enrollmentStudentId
})

usePageMeta(() => ({ title: title.value, icon: brand.favicon }))

const STATUS_COLORS = {
  'Chờ xác nhận': 'text-yellow-500',
  'Đã nhập học': 'text-green-500',
  'Bảo lưu': 'text-blue-500',
  'Thôi học': 'text-gray-500',
}

function statusColor(status) {
  return STATUS_COLORS[status] || 'text-gray-500'
}

const STATUS_OPTIONS = ['Chờ xác nhận', 'Đã nhập học', 'Bảo lưu', 'Thôi học']

const enrollmentStatuses = computed(() =>
  STATUS_OPTIONS.map((s) => ({
    label: s,
    onClick: () => updateStatus(s),
  })),
)

function updateStatus(status) {
  doc.value.enrollment_status = status
  document.save.submit(null, {
    onError: (err) => toast.error(err.messages?.[0] || __('Error updating status')),
  })
}

const tabs = computed(() => [
  { name: 'Activity', label: __('Activity'), icon: ActivityIcon },
  { name: 'Data', label: __('Data'), icon: DetailsIcon },
  { name: 'Tasks', label: __('Tasks'), icon: TaskIcon },
  { name: 'Notes', label: __('Notes'), icon: NoteIcon },
  { name: 'Attachments', label: __('Attachments'), icon: AttachmentIcon },
])

const { tabIndex } = useActiveTabManager(tabs, 'lastEnrollmentStudentTab')

const sections = createResource({
  url: 'crm.fcrm.doctype.crm_fields_layout.crm_fields_layout.get_sidepanel_sections',
  cache: ['sidePanelSections', 'Enrollment Student'],
  params: { doctype: 'Enrollment Student' },
  auto: true,
})
</script>
