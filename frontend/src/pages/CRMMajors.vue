<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs
        v-model="viewControls"
        routeName="CRM Majors"
        :label="__('Ngành & Chương trình')"
      />
    </template>
    <template #right-header>
      <CustomActions
        v-if="listView?.customListActions"
        :actions="listView.customListActions"
      />
      <Button
        v-if="canConfigure"
        variant="solid"
        :label="__('Create')"
        iconLeft="plus"
        @click="createMajor"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="majors"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM Major"
  />
  <CRMMajorsListView
    v-if="majors.data && rows.length"
    ref="listView"
    v-model="majors.data.page_length_count"
    v-model:list="majors"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: majors.data.row_count,
      totalCount: majors.data.total_count,
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
    v-else-if="majors.data && !rows.length"
    name="CRM Major"
    :icon="GraduationCapIcon"
  />
</template>

<script setup>
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import CRMMajorsListView from '@/components/ListViews/CRMMajorsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import ViewControls from '@/components/ViewControls.vue'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { usersStore } from '@/stores/users'
import { formatDate, timeAgo } from '@/utils'
import { canConfigureSystem } from '@/utils/rolePolicy'
import GraduationCapIcon from '~icons/lucide/graduation-cap'
import { computed, ref } from 'vue'

const { showModal } = useDoctypeModal()
const { getUser } = usersStore()

const user = computed(() => getUser() || {})
const canConfigure = computed(() => canConfigureSystem(user.value))

const listView = ref(null)
const majors = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

function createMajor() {
  showModal({
    doctype: 'CRM Major',
    title: __('CRM Major'),
    callbacks: {
      afterInsert: () => {
        majors.value.reload?.()
      },
    },
  })
}

const rows = computed(() => {
  if (
    !majors.value?.data?.data ||
    !['list', 'group_by'].includes(majors.value.data.view_type)
  )
    return []
  return majors.value.data.data.map((item) => {
    let _rows = {}
    majors.value.data.rows.forEach((row) => {
      _rows[row] = item[row]

      let fieldType = majors.value.data.columns?.find(
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
  let _columns = majors.value?.data?.columns || []
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
