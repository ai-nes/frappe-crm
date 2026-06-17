<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs
        v-model="viewControls"
        routeName="CRM Persons"
        :label="__('Persons')"
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
        @click="createCRMPerson"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="crmPersons"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM Person"
  />
  <CRMPersonsListView
    v-if="crmPersons.data && rows.length"
    ref="listView"
    v-model="crmPersons.data.page_length_count"
    v-model:list="crmPersons"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: crmPersons.data.row_count,
      totalCount: crmPersons.data.total_count,
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
    v-else-if="crmPersons.data && !rows.length"
    name="Persons"
    :icon="CRMPersonIcon"
  />
</template>

<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import CRMPersonsListView from '@/components/ListViews/CRMPersonsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewControls from '@/components/ViewControls.vue'
import CRMPersonIcon from '~icons/lucide/user'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { getMeta } from '@/stores/meta'
import { formatDate, timeAgo } from '@/utils'
import { useRouter } from 'vue-router'
import { ref, computed } from 'vue'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('CRM Person')
const { showModal } = useDoctypeModal()
const router = useRouter()

const listView = ref(null)
const crmPersons = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

function createCRMPerson() {
  showModal({
    doctype: 'CRM Person',
    title: __('Person'),
    callbacks: {
      afterInsert: (doc) => {
        router.push({ name: 'CRM Person', params: { crmPersonId: doc.name } })
      },
    },
  })
}

const rows = computed(() => {
  if (
    !crmPersons.value?.data?.data ||
    !['list', 'group_by'].includes(crmPersons.value.data.view_type)
  )
    return []
  return crmPersons.value.data.data.map((crm_person) => {
    let _rows = {}
    crmPersons.value.data.rows.forEach((row) => {
      _rows[row] = crm_person[row]

      let fieldType = crmPersons.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(crm_person[row], '', true, fieldType == 'Datetime')
      }

      if (fieldType && fieldType == 'Currency') {
        _rows[row] = getFormattedCurrency(row, crm_person)
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(crm_person[row]),
          timeAgo: __(timeAgo(crm_person[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = crmPersons.value?.data?.columns || []
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
