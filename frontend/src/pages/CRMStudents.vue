<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs v-model="viewControls" :routeName="funnelTitle" />
    </template>
    <template #right-header>
      <CustomActions
        v-if="listView?.customListActions"
        :actions="listView.customListActions"
      />
      <Button
        variant="solid"
        :label="__('Create')"
        iconLeft="plus"
        @click="createStudent"
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
    name="CRM Students"
    :icon="EnrollmentIcon"
  />
</template>

<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import CRMStudentsListView from '@/components/ListViews/CRMStudentsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewControls from '@/components/ViewControls.vue'
import EnrollmentIcon from '~icons/lucide/graduation-cap'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { getMeta } from '@/stores/meta'
import { formatDate, timeAgo } from '@/utils'
import { useRoute, useRouter } from 'vue-router'
import { ref, computed, watch } from 'vue'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('CRM Student')
const { showModal } = useDoctypeModal()
const route = useRoute()
const router = useRouter()

const funnelStage = computed(() => route.query.stage || 'intake')

const funnelTitle = computed(() => {
  if (funnelStage.value === 'enrolled') {
    return __('Enrolled Students')
  }
  return __('Prospective Students')
})

const funnelFilters = computed(() => {
  if (funnelStage.value === 'enrolled') {
    return { enrollment_status: 'Đã chuyển đổi' }
  }
  return { enrollment_status: ['not in', ['Từ chối']] }
})

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

function createStudent() {
  showModal({
    doctype: 'CRM Student',
    title: __('New CRM Student'),
    callbacks: {
      afterInsert: (doc) => {
        router.push({ name: 'CRM Student', params: { crmStudentId: doc.name } })
      },
    },
  })
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
