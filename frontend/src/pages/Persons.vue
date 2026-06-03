<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs v-model="viewControls" routeName="Persons" />
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
        @click="createPerson"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="persons"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="Person"
  />
  <PersonsListView
    v-if="persons.data && rows.length"
    ref="listView"
    v-model="persons.data.page_length_count"
    v-model:list="persons"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: persons.data.row_count,
      totalCount: persons.data.total_count,
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
    v-else-if="persons.data && !rows.length"
    name="Persons"
    :icon="PersonIcon"
  />
</template>

<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import PersonsListView from '@/components/ListViews/PersonsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewControls from '@/components/ViewControls.vue'
import PersonIcon from '~icons/lucide/user'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { getMeta } from '@/stores/meta'
import { formatDate, timeAgo } from '@/utils'
import { useRouter } from 'vue-router'
import { ref, computed } from 'vue'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('Person')
const { showModal } = useDoctypeModal()
const router = useRouter()

const listView = ref(null)
const persons = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

function createPerson() {
  showModal({
    doctype: 'Person',
    title: __('New Person'),
    callbacks: {
      afterInsert: (doc) => {
        router.push({ name: 'Person', params: { personId: doc.name } })
      },
    },
  })
}

const rows = computed(() => {
  if (
    !persons.value?.data?.data ||
    !['list', 'group_by'].includes(persons.value.data.view_type)
  )
    return []
  return persons.value.data.data.map((person) => {
    let _rows = {}
    persons.value.data.rows.forEach((row) => {
      _rows[row] = person[row]

      let fieldType = persons.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(person[row], '', true, fieldType == 'Datetime')
      }

      if (fieldType && fieldType == 'Currency') {
        _rows[row] = getFormattedCurrency(row, person)
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(person[row]),
          timeAgo: __(timeAgo(person[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = persons.value?.data?.columns || []
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
