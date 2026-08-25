<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs
        v-model="viewControls"
        routeName="CRM Segments"
        :label="__('Segments')"
      />
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
        @click="createCRMSegment"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="crmSegments"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM Segment"
  />
  <CRMSegmentsListView
    v-if="crmSegments.data && rows.length"
    ref="listView"
    v-model="crmSegments.data.page_length_count"
    v-model:list="crmSegments"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: crmSegments.data.row_count,
      totalCount: crmSegments.data.total_count,
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
    v-else-if="crmSegments.data && !rows.length"
    name="Segments"
    :icon="CRMSegmentIcon"
  />
</template>

<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import CRMSegmentsListView from '@/components/ListViews/CRMSegmentsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewControls from '@/components/ViewControls.vue'
import CRMSegmentIcon from '~icons/lucide/filter'
import { formatDate, timeAgo } from '@/utils'
import { useRouter } from 'vue-router'
import { ref, computed } from 'vue'

const router = useRouter()

const listView = ref(null)
const crmSegments = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

function createCRMSegment() {
  router.push({ name: 'CRM Segment', params: { crmSegmentId: 'new' } })
}

const rows = computed(() => {
  if (
    !crmSegments.value?.data?.data ||
    !['list', 'group_by'].includes(crmSegments.value.data.view_type)
  )
    return []
  return crmSegments.value.data.data.map((crm_segment) => {
    let _rows = {}
    crmSegments.value.data.rows.forEach((row) => {
      _rows[row] = crm_segment[row]

      let fieldType = crmSegments.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(crm_segment[row], '', true, fieldType == 'Datetime')
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(crm_segment[row]),
          timeAgo: __(timeAgo(crm_segment[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = crmSegments.value?.data?.columns || []
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
