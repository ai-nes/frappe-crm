<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs
        v-model="viewControls"
        routeName="Lookups"
        :label="__(currentTab.label)"
      />
    </template>
    <template #right-header>
      <CustomActions
        v-if="listView?.customListActions"
        :actions="listView.customListActions"
      />
    </template>
  </LayoutHeader>

  <!-- Sub-tabs bar -->
  <div class="flex border-b border-outline-gray-2 bg-surface-white px-3 sm:px-5">
    <nav class="flex gap-6 overflow-x-auto">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        class="flex items-center gap-2 whitespace-nowrap border-b-2 py-3 text-sm font-medium transition-colors"
        :class="
          activeTabId === tab.id
            ? 'border-ink-gray-9 text-ink-gray-9 font-semibold'
            : 'border-transparent text-ink-gray-5 hover:border-outline-gray-3 hover:text-ink-gray-8'
        "
        @click="selectTab(tab.id)"
      >
        <FeatherIcon :name="tab.icon" class="size-4" />
        <span>{{ __(tab.label) }}</span>
      </button>
    </nav>
  </div>

  <!-- Native Frappe View Controls (Quick filters, Search, Filter, Sort, Columns, Refresh) -->
  <ViewControls
    :key="activeTabId"
    ref="viewControls"
    v-model="currentList"
    v-model:loadMore="loadMore"
    v-model:resizeColumn="triggerResize"
    v-model:updatedPageCount="updatedPageCount"
    :doctype="currentTab.doctype"
  />

  <!-- Native Frappe List View -->
  <ListView
    v-if="currentList.data && rows.length"
    ref="listView"
    :columns="columns"
    :rows="rows"
    :options="{
      selectable: false,
      showTooltip: false,
      resizeColumn: true,
      rowCount: currentList.data.row_count,
      totalCount: currentList.data.total_count,
    }"
    row-key="name"
  >
    <ListHeader
      class="mx-3 sm:mx-5"
      @columnWidthUpdated="() => triggerResize++"
    >
      <ListHeaderItem
        v-for="column in columns"
        :key="column.key"
        :item="column"
        @columnWidthUpdated="() => triggerResize++"
      />
    </ListHeader>
    <ListRows
      v-slot="{ idx, column, item }"
      class="mx-3 sm:mx-5"
      :rows="rows"
      :doctype="currentTab.doctype"
    >
      <ListRowItem :item="item" :align="column.align" class="overflow-hidden">
        <template #default="{ label }">
          <div
            v-if="['modified', 'creation'].includes(column.key)"
            class="truncate text-base"
            @click="(event) => viewControls?.applyFilter({ event, idx, column, item, firstColumn: columns[0] })"
          >
            <Tooltip :text="item.label">
              <div>{{ item.timeAgo }}</div>
            </Tooltip>
          </div>
          <div
            v-else-if="label"
            class="truncate text-base"
            @click="(event) => viewControls?.applyFilter({ event, idx, column, item, firstColumn: columns[0] })"
          >
            {{ label }}
          </div>
        </template>
      </ListRowItem>
    </ListRows>
  </ListView>

  <ListFooter
    v-if="currentList.data && rows.length"
    v-model="updatedPageCount"
    class="border-t sm:px-5 px-3 py-2"
    :options="{
      rowCount: currentList.data.row_count,
      totalCount: currentList.data.total_count,
    }"
    @loadMore="() => loadMore++"
  />

  <EmptyState
    v-else-if="currentList.data && !rows.length"
    :name="currentTab.label"
    :icon="currentTab.iconComponent"
  />
</template>

<script setup>
import CustomActions from '@/components/CustomActions.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import ListRows from '@/components/ListViews/ListRows.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import ViewControls from '@/components/ViewControls.vue'
import { formatDate, timeAgo } from '@/utils'
import CalendarIcon from '~icons/lucide/calendar'
import GraduationCapIcon from '~icons/lucide/graduation-cap'
import MapIcon from '~icons/lucide/map'
import MapPinIcon from '~icons/lucide/map-pin'
import SchoolIcon from '~icons/lucide/school'
import {
  FeatherIcon,
  ListFooter,
  ListHeader,
  ListHeaderItem,
  ListRowItem,
  ListView,
  Tooltip,
  usePageMeta,
} from 'frappe-ui'
import { computed, markRaw, ref } from 'vue'

usePageMeta(() => ({ title: __('Tra cứu tuyển sinh') }))

const tabs = [
  {
    id: 'schools',
    label: __('Trường THPT'),
    icon: 'school',
    iconComponent: markRaw(SchoolIcon),
    doctype: 'CRM High School',
  },
  {
    id: 'majors',
    label: __('Ngành học & Tuyển sinh'),
    icon: 'book-open',
    iconComponent: markRaw(GraduationCapIcon),
    doctype: 'CRM Major',
  },
  {
    id: 'years',
    label: __('Năm tuyển sinh'),
    icon: 'calendar',
    iconComponent: markRaw(CalendarIcon),
    doctype: 'CRM Admission Year',
  },
  {
    id: 'campuses',
    label: __('Cơ sở đào tạo'),
    icon: 'map-pin',
    iconComponent: markRaw(MapPinIcon),
    doctype: 'CRM Campus',
  },
  {
    id: 'provinces',
    label: __('Tỉnh / Thành phố'),
    icon: 'map',
    iconComponent: markRaw(MapIcon),
    doctype: 'CRM Province',
  },
]

const activeTabId = ref('schools')
const currentTab = computed(() => tabs.find((t) => t.id === activeTabId.value) || tabs[0])

const listView = ref(null)
const currentList = ref({})
const loadMore = ref(1)
const triggerResize = ref(1)
const updatedPageCount = ref(20)
const viewControls = ref(null)

function selectTab(tabId) {
  if (activeTabId.value === tabId) return
  activeTabId.value = tabId
  currentList.value = {}
  loadMore.value = 1
  triggerResize.value = 1
}

const rows = computed(() => {
  if (
    !currentList.value?.data?.data ||
    !['list', 'group_by'].includes(currentList.value.data.view_type)
  )
    return []

  return currentList.value.data.data.map((item) => {
    let _rows = {}
    currentList.value.data.rows.forEach((row) => {
      _rows[row] = item[row]

      let fieldType = currentList.value.data.columns?.find(
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
  let _columns = currentList.value?.data?.columns || []
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
