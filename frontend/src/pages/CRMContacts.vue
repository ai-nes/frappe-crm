<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs
        v-model="viewControls"
        routeName="CRM Contacts"
        :label="__('Lead')"
      />
    </template>
    <template #right-header>
      <CustomActions
        v-if="listView?.customListActions"
        :actions="listView.customListActions"
      />
      <Button
        v-if="canSubmitIntake"
        variant="solid"
        :label="__('New Lead')"
        iconLeft="plus"
        @click="createContact"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="contacts"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM Contact"
    :options="{
      allowedViews: ['list', 'group_by', 'kanban'],
    }"
  />
  <KanbanView
    v-if="route.params.viewType == 'kanban'"
    v-model="contacts"
    :options="{
      getRoute: (row) => ({
        name: 'CRM Contact',
        params: { crmContactId: row.name },
        query: { view: route.query.view, viewType: route.params.viewType },
      }),
      onNewClick: (column) => createContact(column),
    }"
    @update="(data) => viewControls.updateKanbanSettings(data)"
    @loadMore="(columnName) => viewControls.loadMoreKanban(columnName)"
  >
    <template #title="{ titleField, itemName }">
      <div class="flex gap-2 items-center">
        <div
          v-if="getRow(itemName, titleField).label"
          class="truncate text-base"
        >
          {{ getRow(itemName, titleField).label }}
        </div>
        <div v-else class="text-ink-gray-4">{{ __('No Title') }}</div>
      </div>
    </template>
    <template #fields="{ fieldName, itemName }">
      <div
        v-if="getRow(itemName, fieldName).label"
        class="truncate flex items-center gap-2"
      >
        <div class="truncate text-base">
          {{ getRow(itemName, fieldName).label }}
        </div>
      </div>
    </template>
  </KanbanView>
  <CRMContactsListView
    v-else-if="contacts.data && rows.length"
    ref="listView"
    v-model="contacts.data.page_length_count"
    v-model:list="contacts"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: contacts.data.row_count,
      totalCount: contacts.data.total_count,
    }"
    @loadMore="() => loadMore++"
    @columnWidthUpdated="() => triggerResize++"
    @updatePageCount="(count) => (updatedPageCount = count)"
    @applyFilter="(data) => viewControls.applyFilter(data)"
    @applyLikeFilter="(data) => viewControls.applyLikeFilter(data)"
    @likeDoc="(data) => viewControls.likeDoc(data)"
    @selectionsChanged="(selections) => viewControls.updateSelections(selections)"
  />
  <EmptyState
    v-else-if="contacts.data && !rows.length"
    name="Lead"
    :icon="ContactIcon"
  />
  <StudentIntakeModal
    v-if="showIntakeModal"
    v-model="showIntakeModal"
    @completed="handleIntakeCompleted"
    @review-required="handleReviewRequired"
  />
  <DecideStudentIntakeReviewModal
    v-if="showReviewModal && intakeReview"
    v-model="showReviewModal"
    :review="intakeReview"
    @resolved="handleIntakeCompleted"
  />
</template>

<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import CRMContactsListView from '@/components/ListViews/CRMContactsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import KanbanView from '@/components/Kanban/KanbanView.vue'
import ViewControls from '@/components/ViewControls.vue'
import StudentIntakeModal from '@/components/Modals/StudentIntakeModal.vue'
import DecideStudentIntakeReviewModal from '@/components/Modals/DecideStudentIntakeReviewModal.vue'
import ContactIcon from '~icons/lucide/users'
import { getMeta } from '@/stores/meta'
import { usersStore } from '@/stores/users'
import { hasAnyCapability } from '@/utils/rolePolicy'
import { formatDate, timeAgo } from '@/utils'
import { useRoute } from 'vue-router'
import { ref, computed } from 'vue'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('CRM Contact')
const route = useRoute()
const { getCurrentUser } = usersStore()

const listView = ref(null)
const contacts = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)
const showIntakeModal = ref(false)
const showReviewModal = ref(false)
const intakeReview = ref(null)
const canSubmitIntake = computed(() =>
  hasAnyCapability(getCurrentUser(), [
    'student.execute',
    'team.oversee',
    'admissions.oversee',
    'system.configure',
  ]),
)

function getRow(name, field) {
  function getValue(value) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return value
    }
    return { label: value }
  }
  return getValue(contacts.value?.data?.data?.find((r) => r.name === name)?.[field])
}

function createContact() {
  showIntakeModal.value = true
}

function handleReviewRequired(review) {
  intakeReview.value = review
  showReviewModal.value = true
}

function handleIntakeCompleted() {
  contacts.value?.reload?.()
  showIntakeModal.value = false
}

const rows = computed(() => {
  if (
    !contacts.value?.data?.data ||
    !['list', 'group_by'].includes(contacts.value.data.view_type)
  )
    return []
  return contacts.value.data.data.map((contact) => {
    let _rows = {}
    contacts.value.data.rows.forEach((row) => {
      _rows[row] = contact[row]

      let fieldType = contacts.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(contact[row], '', true, fieldType == 'Datetime')
      }

      if (fieldType && fieldType == 'Currency') {
        _rows[row] = getFormattedCurrency(row, contact)
      }

      if (fieldType && fieldType == 'Float') {
        _rows[row] = getFormattedFloat(row, contact)
      }

      if (fieldType && fieldType == 'Percent') {
        _rows[row] = getFormattedPercent(row, contact)
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(contact[row]),
          timeAgo: __(timeAgo(contact[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = contacts.value?.data?.columns || []
  if (_columns.length) {
    _columns = _columns.map((col, index) => {
      if (index === _columns.length - 1) {
        return { ...col, align: 'right' }
      }
      return col
    })
  }
  return _columns
})
</script>
