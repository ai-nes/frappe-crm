<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs v-model="viewControls" routeName="CRM Campaigns" />
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
        @click="createCRMCampaign"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="crmCampaigns"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="CRM Campaign"
  />
  <CRMCampaignsListView
    v-if="crmCampaigns.data && rows.length"
    ref="listView"
    v-model="crmCampaigns.data.page_length_count"
    v-model:list="crmCampaigns"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: crmCampaigns.data.row_count,
      totalCount: crmCampaigns.data.total_count,
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
    v-else-if="crmCampaigns.data && !rows.length"
    name="CRM Campaigns"
    :icon="CRMCampaignIcon"
  />
</template>

<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import CRMCampaignsListView from '@/components/ListViews/CRMCampaignsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewControls from '@/components/ViewControls.vue'
import CRMCampaignIcon from '~icons/lucide/megaphone'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { getMeta } from '@/stores/meta'
import { formatDate, timeAgo } from '@/utils'
import { useRouter } from 'vue-router'
import { ref, computed } from 'vue'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('CRM Campaign')
const { showModal } = useDoctypeModal()
const router = useRouter()

const listView = ref(null)
const crmCampaigns = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

function createCRMCampaign() {
  showModal({
    doctype: 'CRM Campaign',
    title: __('New CRM Campaign'),
    callbacks: {
      afterInsert: (doc) => {
        router.push({ name: 'CRM Campaign', params: { crmCampaignId: doc.name } })
      },
    },
  })
}

const rows = computed(() => {
  if (
    !crmCampaigns.value?.data?.data ||
    !['list', 'group_by'].includes(crmCampaigns.value.data.view_type)
  )
    return []
  return crmCampaigns.value.data.data.map((crm_campaign) => {
    let _rows = {}
    crmCampaigns.value.data.rows.forEach((row) => {
      _rows[row] = crm_campaign[row]

      let fieldType = crmCampaigns.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(crm_campaign[row], '', true, fieldType == 'Datetime')
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(crm_campaign[row]),
          timeAgo: __(timeAgo(crm_campaign[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = crmCampaigns.value?.data?.columns || []
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
