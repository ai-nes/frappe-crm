<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs
        v-model="viewControls"
        routeName="CRM Students"
        :label="funnelTitle"
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
        :label="__('New intake')"
        iconLeft="plus"
        @click="showIntakeModal = true"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="students"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM Student"
    :filters="funnelFilters"
    :quickFilterPresets="potentialScoreFilters"
  />
  <CRMStudentsListView
    v-if="students.data && rows.length"
    ref="listView"
    v-model="students.data.page_length_count"
    v-model:list="students"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: students.data.row_count,
      totalCount: students.data.total_count,
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
    v-else-if="students.data && !rows.length"
    name="Students"
    :icon="EnrollmentIcon"
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
import CRMStudentsListView from '@/components/ListViews/CRMStudentsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewControls from '@/components/ViewControls.vue'
import StudentIntakeModal from '@/components/Modals/StudentIntakeModal.vue'
import DecideStudentIntakeReviewModal from '@/components/Modals/DecideStudentIntakeReviewModal.vue'
import EnrollmentIcon from '~icons/lucide/graduation-cap'
import { getMeta } from '@/stores/meta'
import { usersStore } from '@/stores/users'
import { hasAnyCapability } from '@/utils/rolePolicy'
import { formatDate, timeAgo } from '@/utils'
import { useRoute, useRouter } from 'vue-router'
import { ref, computed, watch } from 'vue'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('CRM Student')
const route = useRoute()
const router = useRouter()
const { getCurrentUser } = usersStore()

const funnelStage = computed(() => route.query.stage || 'intake')

const funnelTitle = computed(() => {
  if (funnelStage.value === 'enrolled') {
    return 'Enrolled Students'
  }
  return 'Prospective Students'
})

const funnelFilters = computed(() => {
  if (funnelStage.value === 'enrolled') {
    return { enrollment_status: 'Đã chuyển đổi' }
  }
  return { enrollment_status: ['not in', ['Từ chối']] }
})

const potentialScoreFilters = computed(() => [
  {
    key: 'potential-score',
    label: __('Potential Score'),
    fieldname: '_potential_score_tier',
    fieldtype: 'Select',
    options: [
      { label: __('High Potential'), value: 'high' },
      { label: __('Medium Potential'), value: 'medium' },
      { label: __('Low Potential'), value: 'low' },
    ],
    presetValues: {
      high: 'high',
      medium: 'medium',
      low: 'low',
    },
    after: 'enrollment_status',
  },
])

watch(
  () => route.query.stage,
  () => {
    students.value = {}
    loadMore.value++
  },
)

const listView = ref(null)

const students = ref({})
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

function handleReviewRequired(review) {
  intakeReview.value = review
  showReviewModal.value = true
}

function handleIntakeCompleted(result) {
  students.value?.reload?.()
  const student = result?.student || result?.student_name || result?.case_name
  if (student) {
    showIntakeModal.value = false
    router.push({ name: 'CRM Student', params: { crmStudentId: student } })
  }
}

const rows = computed(() => {
  if (
    !students.value?.data?.data ||
    !['list', 'group_by'].includes(students.value.data.view_type)
  )
    return []
  return students.value.data.data.map((student) => {
    let _rows = {}
    students.value.data.rows.forEach((row) => {
      _rows[row] = student[row]

      let fieldType = students.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(student[row], '', true, fieldType == 'Datetime')
      }

      if (fieldType && fieldType == 'Currency') {
        _rows[row] = getFormattedCurrency(row, student)
      }

      if (fieldType && fieldType == 'Float') {
        _rows[row] = getFormattedFloat(row, student)
      }

      if (fieldType && fieldType == 'Percent') {
        _rows[row] = getFormattedPercent(row, student)
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(student[row]),
          timeAgo: __(timeAgo(student[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = students.value?.data?.columns || []
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
