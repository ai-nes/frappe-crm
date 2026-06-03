<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs v-model="viewControls" routeName="Campaigns" />
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
        @click="createCampaign"
      />
    </template>
  </LayoutHeader>
  <ViewControls
    ref="viewControls"
    v-model="campaigns"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    doctype="Campaign"
  />
  <CampaignsListView
    v-if="campaigns.data && rows.length"
    ref="listView"
    v-model="campaigns.data.page_length_count"
    v-model:list="campaigns"
    :rows="rows"
    :columns="columns"
    :options="{
      showTooltip: false,
      resizeColumn: true,
      rowCount: campaigns.data.row_count,
      totalCount: campaigns.data.total_count,
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
    v-else-if="campaigns.data && !rows.length"
    name="Campaigns"
    :icon="CampaignIcon"
  />
</template>

<script setup>
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import CampaignsListView from '@/components/ListViews/CampaignsListView.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ViewControls from '@/components/ViewControls.vue'
import CampaignIcon from '~icons/lucide/megaphone'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { getMeta } from '@/stores/meta'
import { formatDate, timeAgo } from '@/utils'
import { useRouter } from 'vue-router'
import { ref, computed } from 'vue'

const { getFormattedPercent, getFormattedFloat, getFormattedCurrency } =
  getMeta('Campaign')
const { showModal } = useDoctypeModal()
const router = useRouter()

const listView = ref(null)
const campaigns = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

function createCampaign() {
  showModal({
    doctype: 'Campaign',
    title: __('New Campaign'),
    callbacks: {
      afterInsert: (doc) => {
        router.push({ name: 'Campaign', params: { campaignId: doc.name } })
      },
    },
  })
}

const rows = computed(() => {
  if (
    !campaigns.value?.data?.data ||
    !['list', 'group_by'].includes(campaigns.value.data.view_type)
  )
    return []
  return campaigns.value.data.data.map((campaign) => {
    let _rows = {}
    campaigns.value.data.rows.forEach((row) => {
      _rows[row] = campaign[row]

      let fieldType = campaigns.value.data.columns?.find(
        (col) => (col.key || col.value) == row,
      )?.type

      if (
        fieldType &&
        ['Date', 'Datetime'].includes(fieldType) &&
        !['modified', 'creation'].includes(row)
      ) {
        _rows[row] = formatDate(campaign[row], '', true, fieldType == 'Datetime')
      }

      if (['modified', 'creation'].includes(row)) {
        _rows[row] = {
          label: formatDate(campaign[row]),
          timeAgo: __(timeAgo(campaign[row])),
        }
      }
    })
    return _rows
  })
})

const columns = computed(() => {
  let _columns = campaigns.value?.data?.columns || []
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
