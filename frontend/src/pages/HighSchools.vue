<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs v-model="viewControls" routeName="High Schools" />
    </template>
    <template #right-header>
      <CustomActions
        v-if="listView?.customListActions"
        :actions="listView.customListActions"
      />
      <GeographyImportButton variant="subtle" @imported="reloadHighSchools" />
      <Button
        variant="solid"
        :label="__('Create')"
        iconLeft="plus"
        @click="createHighSchool"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="highSchools"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM High School"
  />
  <HighSchoolsListView
    v-if="highSchools.data && rows.length"
    ref="listView"
    v-model="highSchools.data.page_length_count"
    v-model:list="highSchools"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: highSchools.data.row_count,
      totalCount: highSchools.data.total_count,
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
    v-else-if="highSchools.data && !rows.length"
    name="High Schools"
    :icon="SchoolIcon"
  />
</template>

<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import HighSchoolsListView from '@/components/ListViews/HighSchoolsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewControls from '@/components/ViewControls.vue'
import GeographyImportButton from '@/components/GeographyImportButton.vue'
import SchoolIcon from '~icons/lucide/school'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { getMeta } from '@/stores/meta'
import { formatDate, timeAgo } from '@/utils'
import { useRouter } from 'vue-router'
import { ref, computed } from 'vue'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('CRM High School')
const { showModal } = useDoctypeModal()
const router = useRouter()

const listView = ref(null)
const highSchools = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

function createHighSchool() {
  showModal({
    doctype: 'CRM High School',
    title: __('High School'),
    callbacks: {
      afterInsert: (doc) => {
        router.push({ name: 'High School', params: { highSchoolId: doc.name } })
      },
    },
  })
}

function reloadHighSchools() {
  highSchools.value.reload?.()
}

const rows = computed(() => {
  if (
    !highSchools.value?.data?.data ||
    !['list', 'group_by'].includes(highSchools.value.data.view_type)
  )
    return []
  return highSchools.value.data.data.map((hs) => {
    let _rows = {}
    highSchools.value.data.rows.forEach((row) => {
      _rows[row] = hs[row]

      let fieldType = highSchools.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(hs[row], '', true, fieldType == 'Datetime')
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(hs[row]),
          timeAgo: __(timeAgo(hs[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = highSchools.value?.data?.columns || []
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
