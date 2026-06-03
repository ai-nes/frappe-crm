<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs v-model="viewControls" routeName="CRM Events" />
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
        @click="createEvent"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="events"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM Event"
  />
  <CRMEventsListView
    v-if="events.data && rows.length"
    ref="listView"
    v-model="events.data.page_length_count"
    v-model:list="events"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: events.data.row_count,
      totalCount: events.data.total_count,
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
    v-else-if="events.data && !rows.length"
    name="CRM Events"
    :icon="EventIcon"
  />
</template>

<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import CRMEventsListView from '@/components/ListViews/CRMEventsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewControls from '@/components/ViewControls.vue'
import EventIcon from '~icons/lucide/calendar'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { getMeta } from '@/stores/meta'
import { formatDate, timeAgo } from '@/utils'
import { useRouter } from 'vue-router'
import { ref, computed } from 'vue'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('CRM Event')
const { showModal } = useDoctypeModal()
const router = useRouter()

const listView = ref(null)
const events = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

function createEvent() {
  showModal({
    doctype: 'CRM Event',
    title: __('New CRM Event'),
    callbacks: {
      afterInsert: (doc) => {
        router.push({ name: 'CRM Event', params: { crmEventId: doc.name } })
      },
    },
  })
}

const rows = computed(() => {
  if (
    !events.value?.data?.data ||
    !['list', 'group_by'].includes(events.value.data.view_type)
  )
    return []
  return events.value.data.data.map((ev) => {
    let _rows = {}
    events.value.data.rows.forEach((row) => {
      _rows[row] = ev[row]

      let fieldType = events.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(ev[row], '', true, fieldType == 'Datetime')
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(ev[row]),
          timeAgo: __(timeAgo(ev[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = events.value?.data?.columns || []
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
