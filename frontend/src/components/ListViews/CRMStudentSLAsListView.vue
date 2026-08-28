<template>
  <ListView
    :class="$attrs.class"
    :columns="columns"
    :rows="rows"
    :options="{
      selectable: options.selectable,
      showTooltip: options.showTooltip,
      resizeColumn: options.resizeColumn,
    }"
    row-key="name"
    @update:selections="(selections) => emit('selectionsChanged', selections)"
  >
    <ListHeader
      class="mx-3 sm:mx-5"
      @columnWidthUpdated="emit('columnWidthUpdated')"
    >
      <ListHeaderItem
        v-for="column in columns"
        :key="column.key"
        :item="column"
        @columnWidthUpdated="emit('columnWidthUpdated', column)"
      />
    </ListHeader>
    <ListRows
      v-slot="{ idx, column, item }"
      class="mx-3 sm:mx-5"
      :rows="rows"
      doctype="CRM Student SLA Attempt"
    >
      <ListRowItem :item="item" :align="column.align" class="overflow-hidden">
        <template #default="{ label }">
          <div
            v-if="['modified', 'creation'].includes(column.key)"
            class="truncate text-base"
            @click="(event) => emit('applyFilter', { event, idx, column, item, firstColumn: columns[0] })"
          >
            <Tooltip :text="item.label">
              <div>{{ item.timeAgo }}</div>
            </Tooltip>
          </div>
          <div
            v-else-if="column.key === 'status'"
            class="truncate"
            @click="(event) => emit('applyFilter', { event, idx, column, item, firstColumn: columns[0] })"
          >
            <Badge
              v-if="item"
              :label="slaStatusPresentation(item).label"
              :theme="slaStatusPresentation(item).theme"
              variant="subtle"
              size="md"
            />
          </div>
          <div
            v-else-if="column.key === 'student'"
            class="truncate text-base font-medium text-ink-gray-9 hover:underline cursor-pointer"
            @click.stop="openStudent(item)"
          >
            {{ label || item }}
          </div>
          <div
            v-else-if="column.type === 'Check'"
            class="flex items-center"
          >
            <FormControl
              type="checkbox"
              :modelValue="item"
              :disabled="true"
              class="text-ink-gray-9"
            />
          </div>
          <div
            v-else-if="label"
            class="truncate text-base"
            @click="(event) => emit('applyFilter', { event, idx, column, item, firstColumn: columns[0] })"
          >
            {{ label }}
          </div>
        </template>
      </ListRowItem>
    </ListRows>
    <ListSelectBanner>
      <template #actions="{ selections, unselectAll }">
        <Dropdown
          :options="listBulkActionsRef?.bulkActions(selections, unselectAll)"
        >
          <Button icon="more-horizontal" variant="ghost" />
        </Dropdown>
      </template>
    </ListSelectBanner>
  </ListView>
  <ListFooter
    v-if="pageLengthCount"
    v-model="pageLengthCount"
    class="border-t sm:px-5 px-3 py-2"
    :options="{
      rowCount: options.rowCount,
      totalCount: options.totalCount,
    }"
    @loadMore="emit('loadMore')"
  />
  <ListBulkActions ref="listBulkActionsRef" v-model="list" doctype="CRM Student SLA Attempt" />
</template>

<script setup>
import ListBulkActions from '@/components/ListBulkActions.vue'
import ListRows from '@/components/ListViews/ListRows.vue'
import { slaStatusPresentation } from '@/utils/studentSLA'
import {
  Badge,
  Button,
  Dropdown,
  FormControl,
  ListFooter,
  ListHeader,
  ListHeaderItem,
  ListRowItem,
  ListSelectBanner,
  ListView,
  Tooltip,
} from 'frappe-ui'
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'

defineProps({
  rows: { type: Array, required: true },
  columns: { type: Array, required: true },
  options: {
    type: Object,
    default: () => ({
      selectable: true,
      showTooltip: true,
      resizeColumn: false,
      totalCount: 0,
      rowCount: 0,
    }),
  },
})
const emit = defineEmits([
  'loadMore',
  'updatePageCount',
  'columnWidthUpdated',
  'applyFilter',
  'applyLikeFilter',
  'likeDoc',
  'selectionsChanged',
])

const router = useRouter()
const pageLengthCount = defineModel({ type: Number })
const list = defineModel('list', { type: Object })
const listBulkActionsRef = ref(null)

function openStudent(studentId) {
  if (!studentId) return
  router.push({ name: 'CRM Student', params: { crmStudentId: studentId } })
}

watch(pageLengthCount, (val, old_value) => {
  if (val === old_value) return
  emit('updatePageCount', val)
})

defineExpose({ customListActions: null })
</script>

