<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs routeName="Assignment Overview" :label="__('Cơ chế phân bổ')" />
    </template>
    <template #right-header>
      <Button
        variant="subtle"
        :label="__('Làm mới')"
        iconLeft="refresh-cw"
        :loading="overview.loading || readiness.loading"
        @click="refresh"
      />
    </template>
  </LayoutHeader>

  <main class="assignment-overview h-full overflow-y-auto bg-surface-gray-2/40 p-4 sm:p-5">
    <div class="mx-auto max-w-[1600px] space-y-5">
      <section class="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div class="flex items-center gap-2">
            <FeatherIcon name="git-merge" class="size-6 text-blue-600" aria-hidden="true" />
            <h1 class="text-2xl font-semibold text-ink-gray-9">{{ __('Cơ chế phân bổ Lead') }}</h1>
          </div>
          <div
            v-if="summary"
            class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-gray-6"
            :aria-label="__('Tóm tắt phân bổ')"
          >
            <span><strong class="tabular-nums font-semibold text-ink-gray-9">{{ summary.zones || 0 }}</strong> {{ __('địa bàn') }}</span>
            <span><strong class="tabular-nums font-semibold text-ink-gray-9">{{ summary.schools || 0 }}</strong> {{ __('trường') }}</span>
            <span><strong class="tabular-nums font-semibold text-ink-gray-9">{{ summary.teams || 0 }}</strong> {{ __('nhóm') }}</span>
            <span><strong class="tabular-nums font-semibold text-ink-gray-9">{{ summary.staff || 0 }}</strong> {{ __('nhân sự') }}</span>
            <span><strong class="tabular-nums font-semibold text-ink-gray-9">{{ summary.active_students || 0 }}</strong> {{ __('Lead hoạt động') }}</span>
            <span v-if="summary.direct_school_mappings" class="text-blue-700"><strong class="tabular-nums font-semibold">{{ summary.direct_school_mappings }}</strong> {{ __('trường gán riêng') }}</span>
            <span v-if="summary.zone_inherited_school_mappings" class="text-blue-700"><strong class="tabular-nums font-semibold">{{ summary.zone_inherited_school_mappings }}</strong> {{ __('trường theo địa bàn') }}</span>
            <span v-if="summary.unresolved_school_mappings" class="text-orange-700"><strong class="tabular-nums font-semibold">{{ summary.unresolved_school_mappings }}</strong> {{ __('trường cần setup') }}</span>
            <span v-if="summary.unassigned_rows" class="text-orange-700"><strong class="tabular-nums font-semibold">{{ summary.unassigned_rows }}</strong> {{ __('dòng cần setup') }}</span>
          </div>
        </div>
        <span v-if="data?.contractStatus === 'partial'" class="rounded-full bg-orange-50 px-3 py-1 text-xs font-medium text-orange-800">
          {{ __('Schema chưa đầy đủ') }}
        </span>
      </section>

      <div v-if="overview.error" class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">
        <p class="font-medium">{{ __('Không thể tải cấu hình phân bổ') }}</p>
        <p class="mt-1">{{ errorMessage(overview.error) }}</p>
        <Button class="mt-3" :label="__('Thử lại')" @click="refresh" />
      </div>

      <SetupReadinessPanel
        v-if="canViewReadiness && readiness.data"
        :data="readiness.data"
        :loading="readiness.loading"
        @refresh="refresh"
      />
      <section v-else-if="canViewReadiness && readiness.error" class="rounded-lg border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900">
        <p class="font-medium">{{ __('Không thể kiểm tra trạng thái tài khoản') }}</p>
        <p class="mt-1">{{ errorMessage(readiness.error) }}</p>
      </section>
      <section v-else class="rounded-lg border border-blue-100 bg-blue-50/70 p-4 text-sm text-blue-900">
        <div class="flex gap-2">
          <FeatherIcon name="info" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <p>{{ __('Bạn đang xem phần phân bổ trong phạm vi Team. Phần kiểm tra User → Role → Permission Profile chỉ hiển thị cho System Manager.') }}</p>
        </div>
      </section>

      <AssignmentOverviewFilters
        :model-value="filters"
        :schema="data?.filter_schema"
        @update:modelValue="applyFilters"
        @reset="resetFilters"
      />

      <div
        v-if="canEditTopology && selectedSchoolRows.length"
        class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-violet-200 bg-violet-50/70 px-4 py-3 text-sm text-violet-950"
        data-testid="assignment-batch-toolbar"
      >
        <span class="font-medium">{{ __('Đã chọn {0} trường THPT', [selectedSchoolRows.length]) }}</span>
        <Button
          variant="solid"
          :label="__('Thiết lập batch')"
          iconLeft="copy"
          data-testid="open-assignment-batch"
          @click="batchOpen = true"
        />
      </div>

      <AssignmentOverviewTable
        :rows="normalizedRows"
        :loading="overview.loading"
        :next-cursor="nextCursor"
        :active-filter-count="activeFilterCount"
        :selectable="canEditTopology"
        :selected-school-ids="selectedSchoolIds"
        @select="selectRow"
        @load-more="loadMore"
        @toggle-school="toggleSchool"
        @toggle-all-schools="toggleAllSchools"
      />
      <p v-if="data?.warnings?.length" class="rounded-lg border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900">
        <span v-for="warning in data.warnings" :key="warning.code" class="block">{{ warning.message }}</span>
      </p>
    </div>
  </main>

  <AssignmentDetailDrawer
    :row="selectedRow"
    :can-edit="canEditTopology"
    @close="selectedRow = null"
    @edit="openEditor"
  />
  <EditAssignmentModal
    v-model="editOpen"
    :row="editingRow"
    :options="data?.edit_options"
    @applied="handleApplied"
  />
  <BatchAssignmentModal
    v-model="batchOpen"
    :rows="selectedSchoolRows"
    :options="data?.edit_options"
    @applied="handleBatchApplied"
  />
</template>

<script setup>
import { Button, FeatherIcon } from 'frappe-ui'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LayoutHeader from '@/components/LayoutHeader.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import AssignmentOverviewFilters from '@/components/AssignmentWorkspace/AssignmentOverviewFilters.vue'
import AssignmentOverviewTable from '@/components/AssignmentWorkspace/AssignmentOverviewTable.vue'
import AssignmentDetailDrawer from '@/components/AssignmentWorkspace/AssignmentDetailDrawer.vue'
import EditAssignmentModal from '@/components/AssignmentWorkspace/EditAssignmentModal.vue'
import BatchAssignmentModal from '@/components/AssignmentWorkspace/BatchAssignmentModal.vue'
import SetupReadinessPanel from '@/components/AssignmentWorkspace/SetupReadinessPanel.vue'
import {
  assignmentWorkspaceFilterQuery,
  createAssignmentWorkspaceResource,
  normalizeAssignmentWorkspaceRows,
  serializeAssignmentWorkspaceFilters,
} from '@/data/assignmentWorkspace'
import { usersStore } from '@/stores/users'
import { canConfigureSystem } from '@/utils/rolePolicy'

const route = useRoute()
const router = useRouter()
const { getUser } = usersStore()
const currentUser = computed(() => getUser() || {})
const canViewReadiness = computed(() => canConfigureSystem(currentUser.value))

const overview = createAssignmentWorkspaceResource('overview')
const readiness = createAssignmentWorkspaceResource('readiness')
const data = computed(() => overview.data)
const summary = computed(() => data.value?.summary || null)
const normalizedRows = computed(() => normalizeAssignmentWorkspaceRows(rows.value))
const nextCursor = computed(() => data.value?.next_cursor || null)
const canEditTopology = computed(() => Boolean(data.value?.capabilities?.can_edit_topology))
const rows = ref([])
const selectedRow = ref(null)
const editingRow = ref(null)
const batchOpen = ref(false)
const selectedSchoolIds = ref([])
const selectedSchoolRows = computed(() =>
  rows.value.filter((row) => row.level === 'high_school' && selectedSchoolIds.value.includes(row.high_school_id)),
)
const editOpen = computed({
  get: () => Boolean(editingRow.value),
  set: (value) => {
    if (!value) editingRow.value = null
  },
})
const filters = reactive({
  campus: route.query.campus || undefined,
  province: route.query.province || undefined,
  cluster: route.query.cluster || undefined,
  zone: route.query.zone || undefined,
  school: route.query.school || undefined,
  team: route.query.team || undefined,
  staff: route.query.staff || undefined,
  status: route.query.status || undefined,
  workload: route.query.workload || undefined,
  search: route.query.search || undefined,
})
const activeFilterCount = computed(
  () => Object.values(filters).filter((value) => value !== undefined && value !== null && value !== '' && value !== 'all').length,
)

function requestParams(cursor) {
  return {
    filters: serializeAssignmentWorkspaceFilters(filters),
    limit: 100,
    cursor,
  }
}

async function reload({ append = false } = {}) {
  const result = await overview.submit(requestParams(append ? nextCursor.value : undefined))
  const payload = result || overview.data
  rows.value = append ? [...rows.value, ...(payload?.rows || [])] : payload?.rows || []
}

async function refresh() {
  await Promise.all([reload(), canViewReadiness.value ? readiness.fetch() : Promise.resolve()])
}

async function applyFilters(next) {
  for (const key of Object.keys(filters)) {
    if (!(key in next)) delete filters[key]
  }
  Object.assign(filters, next)
  await router.replace({ query: assignmentWorkspaceFilterQuery(filters) })
  selectedSchoolIds.value = []
  await reload()
}

async function resetFilters() {
  for (const key of Object.keys(filters)) delete filters[key]
  await router.replace({ query: {} })
  selectedSchoolIds.value = []
  await reload()
}

async function loadMore() {
  if (nextCursor.value) await reload({ append: true })
}

function selectRow(row) {
  selectedRow.value = row
}

function openEditor(row) {
  selectedRow.value = null
  editingRow.value = row
}

function toggleSchool(highSchoolId) {
  if (!highSchoolId) return
  const selected = new Set(selectedSchoolIds.value)
  if (selected.has(highSchoolId)) selected.delete(highSchoolId)
  else selected.add(highSchoolId)
  selectedSchoolIds.value = [...selected]
}

function toggleAllSchools(ids) {
  const selected = new Set(selectedSchoolIds.value)
  const allSelected = ids.length && ids.every((id) => selected.has(id))
  ids.forEach((id) => (allSelected ? selected.delete(id) : selected.add(id)))
  selectedSchoolIds.value = [...selected]
}

async function handleApplied(result) {
  editingRow.value = null
  selectedRow.value = null
  await refresh()
  if (result?.conflict) return
}

async function handleBatchApplied(result) {
  batchOpen.value = false
  selectedSchoolIds.value = []
  await refresh()
  if (result?.conflict) return
}

function errorMessage(error) {
  return error?.messages?.join?.(' ') || error?.message || String(error || __('Lỗi không xác định'))
}

onMounted(refresh)
</script>

<style scoped>
.assignment-overview {
  min-height: calc(100vh - 7rem);
}
</style>
