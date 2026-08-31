<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs
        v-model="viewControls"
        routeName="CRM Student SLA Attempts"
        :label="slaTitle"
      />
    </template>
    <template #right-header>
      <CustomActions
        v-if="listView?.customListActions"
        :actions="listView.customListActions"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    :key="slaTab"
    ref="viewControls"
    v-model="slaAttempts"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM Student SLA Attempt"
    :filters="slaFilters"
    :cache-resource="false"
  />
  <CRMStudentSLAsListView
    v-if="slaAttempts.data && rows.length"
    ref="listView"
    v-model="slaAttempts.data.page_length_count"
    v-model:list="slaAttempts"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: slaAttempts.data.row_count,
      totalCount: slaAttempts.data.total_count,
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
    v-else-if="slaAttempts.data && !rows.length"
    name="CRM Student SLA Attempt"
    :icon="ClockIcon"
  />
</template>

<script setup>
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import CRMStudentSLAsListView from '@/components/ListViews/CRMStudentSLAsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import ViewControls from '@/components/ViewControls.vue'
import { formatDate, timeAgo } from '@/utils'
import ClockIcon from '~icons/lucide/clock'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const listView = ref(null)
const slaAttempts = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

const slaTab = computed(() => route.query.tab || '')

const slaTitle = computed(() => {
  const titles = {
    running: __('SLA đang chạy'),
    near_breach: __('SLA sắp trễ (<30 phút)'),
    breached: __('SLA đã trễ'),
    history: __('Lịch sử vi phạm SLA'),
  }
  return titles[slaTab.value] || __('Danh sách SLA')
})

const slaFilters = computed(() => {
  if (slaTab.value === 'running') {
    return { status: ['in', ['open', 'warned', 'paused']] }
  }
  if (slaTab.value === 'near_breach') {
    return { status: 'warned' }
  }
  if (slaTab.value === 'breached') {
    return { status: ['in', ['breached', 'escalated']] }
  }
  if (slaTab.value === 'history') {
    return { status: ['in', ['breached', 'escalated', 'closed', 'closed_inactive', 'superseded']] }
  }
  return {}
})

const rows = computed(() => {
  if (
    !slaAttempts.value?.data?.data ||
    !['list', 'group_by'].includes(slaAttempts.value.data.view_type)
  )
    return []
  return slaAttempts.value.data.data.map((item) => {
    let _rows = {}
    slaAttempts.value.data.rows.forEach((row) => {
      _rows[row] = item[row]

      let fieldType = slaAttempts.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(item[row], '', true, fieldType == 'Datetime')
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(item[row]),
          timeAgo: __(timeAgo(item[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = slaAttempts.value?.data?.columns || []
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
