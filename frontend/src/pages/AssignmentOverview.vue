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
        :loading="overview.loading || readiness.loading || routingControl.loading"
        @click="refresh"
      />
    </template>
  </LayoutHeader>

  <main class="assignment-overview h-full overflow-y-auto bg-surface-gray-2/40 p-4 sm:p-5">
    <div class="mx-auto max-w-[1600px] space-y-5">
      <div v-if="overview.error" class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">
        <p class="font-medium">{{ __('Không thể tải cấu hình phân bổ') }}</p>
        <p class="mt-1">{{ errorMessage(overview.error) }}</p>
        <Button class="mt-3" :label="__('Thử lại')" @click="refresh" />
      </div>

      <Tabs
        v-model="tabIndex"
        :tabs="workspaceTabs"
        class="assignment-workspace-tabs flex flex-col overflow-hidden rounded-xl border border-outline-gray-2 bg-surface-white shadow-sm [&_[role='tablist']]:overflow-x-auto [&_[role='tablist']]:px-4 [&_[role='tablist']]:sm:px-5 [&_[role='tablist']]:min-h-[52px] [&_[role='tablist']]:gap-6 [&_[role='tabpanel']:not([hidden])]:block"
      >
        <template #tab-panel="{ tab }">
          <div v-if="tab.key === 'summary'" class="space-y-4 p-4 sm:p-5">
            <div class="rounded-xl border border-blue-100 bg-blue-50/60 p-5">
              <div class="flex items-start gap-3">
                <FeatherIcon name="compass" class="mt-0.5 size-5 shrink-0 text-blue-700" aria-hidden="true" />
                <div>
                  <h2 class="font-semibold text-blue-950">{{ __('Bối cảnh phân công Lead tự động') }}</h2>
                  <p class="mt-1 max-w-4xl text-sm leading-6 text-blue-900">{{ __('Lead mới đi vào Pool → policy xác định chiến lược → hệ thống kiểm tra Team, Staff active và capacity → chọn Sale → ghi nhận người phụ trách. Nếu thiếu địa bàn, policy hoặc capacity, Lead ở lại hàng chờ để xử lý an toàn.') }}</p>
                </div>
              </div>
            </div>
            <div v-if="routingControl.data" class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div class="rounded-xl border border-outline-gray-2 bg-surface-white p-4"><p class="text-xs text-ink-gray-5">{{ __('Tự động phân công') }}</p><p class="mt-2 text-lg font-semibold" :class="routingControl.data.enabled ? 'text-green-700' : 'text-ink-gray-8'">{{ routingControl.data.enabled ? __('Đang bật') : __('Đang tắt') }}</p><p class="mt-1 text-xs text-ink-gray-5">{{ routingControl.data.ready_to_enable ? __('Sẵn sàng vận hành') : __('Còn mục cần setup') }}</p></div>
              <div class="rounded-xl border border-outline-gray-2 bg-surface-white p-4"><p class="text-xs text-ink-gray-5">{{ __('Sale trong cân bằng tải') }}</p><p class="mt-2 text-lg font-semibold text-ink-gray-9">{{ routingControl.data.summary?.eligible_staff || 0 }}</p><p class="mt-1 text-xs text-ink-gray-5">{{ routingControl.data.summary?.capacity_configured || 0 }} {{ __('đã đặt capacity') }}</p></div>
              <div class="rounded-xl border border-outline-gray-2 bg-surface-white p-4"><p class="text-xs text-ink-gray-5">{{ __('Lead đang giữ') }}</p><p class="mt-2 text-lg font-semibold text-ink-gray-9">{{ routingControl.data.summary?.active_leads || 0 }}</p><p class="mt-1 text-xs text-ink-gray-5">{{ routingControl.data.summary?.remaining_capacity || 0 }} {{ __('chỗ còn trống') }}</p></div>
              <div class="rounded-xl border border-outline-gray-2 bg-surface-white p-4"><p class="text-xs text-ink-gray-5">{{ __('Policy đang hiệu lực') }}</p><p class="mt-2 text-lg font-semibold text-ink-gray-9">{{ routingControl.data.policies?.filter((policy) => policy.status === 'active').length || 0 }}</p><p class="mt-1 text-xs text-ink-gray-5">{{ __('Kiểm tra ở tab Chính sách') }}</p></div>
            </div>
            <div class="grid gap-4 lg:grid-cols-2">
              <div class="rounded-xl border border-outline-gray-2 bg-surface-white p-5"><h3 class="font-semibold text-ink-gray-9">{{ __('Thứ tự setup') }}</h3><ol class="mt-3 space-y-3 text-sm text-ink-gray-7"><li><span class="mr-2 inline-flex size-6 items-center justify-center rounded-full bg-blue-50 text-xs font-semibold text-blue-700">1</span>{{ __('Cấu hình Staff, Team và địa bàn trong Cây phân bổ.') }}</li><li><span class="mr-2 inline-flex size-6 items-center justify-center rounded-full bg-blue-50 text-xs font-semibold text-blue-700">2</span>{{ __('Đặt capacity cho từng Sale ở tab Cân bằng tải.') }}</li><li><span class="mr-2 inline-flex size-6 items-center justify-center rounded-full bg-blue-50 text-xs font-semibold text-blue-700">3</span>{{ __('Tạo và phê duyệt policy cho từng Pool.') }}</li><li><span class="mr-2 inline-flex size-6 items-center justify-center rounded-full bg-blue-50 text-xs font-semibold text-blue-700">4</span>{{ __('Kiểm tra sẵn sàng rồi bật tự động phân công.') }}</li></ol></div>
              <div class="rounded-xl border border-outline-gray-2 bg-surface-white p-5"><h3 class="font-semibold text-ink-gray-9">{{ __('Quy tắc cân bằng tải') }}</h3><ul class="mt-3 space-y-2 text-sm text-ink-gray-7"><li>• {{ __('Dưới 85%: có thể nhận Lead bình thường.') }}</li><li>• {{ __('Từ 85% đến dưới 100%: hiển thị gần đầy; ưu tiên match trường nếu có.') }}</li><li>• {{ __('Từ 100%: không nhận thêm Lead tự động.') }}</li><li>• {{ __('Chưa đặt capacity: không được bật routing mới.') }}</li></ul></div>
            </div>
          </div>

          <div v-else-if="tab.key === 'tree'" class="space-y-4 p-4 sm:p-5">
            <AssignmentOverviewFilters :model-value="filters" :schema="data?.filter_schema" @update:modelValue="applyFilters" @reset="resetFilters" />
            <div v-if="canEditTopology && selectedSchoolRows.length" class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-violet-200 bg-violet-50/70 px-4 py-3 text-sm text-violet-950" data-testid="assignment-batch-toolbar"><span class="font-medium">{{ __('Đã chọn {0} trường THPT', [selectedSchoolRows.length]) }}</span><Button variant="solid" :label="__('Thiết lập batch')" iconLeft="copy" data-testid="open-assignment-batch" @click="batchOpen = true" /></div>
            <AssignmentOverviewTable :rows="normalizedRows" :loading="overview.loading" :next-cursor="nextCursor" :active-filter-count="activeFilterCount" :selectable="canEditTopology" :selected-school-ids="selectedSchoolIds" @select="selectRow" @load-more="loadMore" @toggle-school="toggleSchool" @toggle-all-schools="toggleAllSchools" />
            <p v-if="data?.warnings?.length" class="rounded-lg border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900"><span v-for="warning in data.warnings" :key="warning.code" class="block">{{ warning.message }}</span></p>
          </div>

          <div v-else-if="tab.key === 'control'" class="p-4 sm:p-5"><AssignmentRoutingControlPanel :control="routingControl.data" :loading="routingControl.loading" :saving="controlSaving" :error="routingControl.error" :can-manage="canManageControl" @refresh="refreshControl" @toggle="toggleRouting" /></div>
          <div v-else-if="tab.key === 'load'" class="p-4 sm:p-5"><AssignmentLoadBalancePanel :staff-load="routingControl.data?.staff_load || []" :loading="routingControl.loading" :saving="capacitySaving" :can-manage="canManageControl" @refresh="refreshControl" @save-capacity="saveCapacity" /></div>
          <div v-else-if="tab.key === 'policy'" class="p-4 sm:p-5"><AssignmentPolicyPanel :policies="routingControl.data?.policies || []" :options="routingControl.data?.policy_options || {}" :can-manage="canManageControl" :can-approve="routingControl.data?.can_approve_policy" @changed="refreshControl" /></div>
          <div v-else class="p-4 sm:p-5">
            <SetupReadinessPanel v-if="canViewReadiness && readiness.data" :data="readiness.data" :loading="readiness.loading" @refresh="refresh" />
            <section v-else-if="canViewReadiness && readiness.error" class="rounded-lg border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900"><p class="font-medium">{{ __('Không thể kiểm tra trạng thái tài khoản') }}</p><p class="mt-1">{{ errorMessage(readiness.error) }}</p></section>
            <section v-else class="rounded-lg border border-blue-100 bg-blue-50/70 p-4 text-sm text-blue-900"><div class="flex gap-2"><FeatherIcon name="info" class="mt-0.5 size-4 shrink-0" aria-hidden="true" /><p>{{ __('Bạn đang xem phần phân bổ trong phạm vi Team. Phần kiểm tra User → Role → Permission Profile chỉ hiển thị cho System Manager.') }}</p></div></section>
          </div>
        </template>
      </Tabs>
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
import { Button, FeatherIcon, Tabs, createResource, toast } from 'frappe-ui'
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
import AssignmentRoutingControlPanel from '@/components/AssignmentWorkspace/AssignmentRoutingControlPanel.vue'
import AssignmentLoadBalancePanel from '@/components/AssignmentWorkspace/AssignmentLoadBalancePanel.vue'
import AssignmentPolicyPanel from '@/components/AssignmentWorkspace/AssignmentPolicyPanel.vue'
import {
  assignmentWorkspaceFilterQuery,
  assignmentWorkspaceMethods,
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
const canManageControl = computed(() => canConfigureSystem(currentUser.value))
const tabIndex = ref(0)
const controlSaving = ref(false)
const capacitySaving = ref(false)
const workspaceTabs = [
  { key: 'summary', name: 'summary', label: __('Tổng quan') },
  { key: 'tree', name: 'tree', label: __('Cây phân bổ') },
  { key: 'control', name: 'control', label: __('Điều khiển tự động') },
  { key: 'load', name: 'load', label: __('Cân bằng tải') },
  { key: 'policy', name: 'policy', label: __('Chính sách') },
  { key: 'readiness', name: 'readiness', label: __('Kiểm tra sẵn sàng') },
]

const overview = createAssignmentWorkspaceResource('overview')
const readiness = createAssignmentWorkspaceResource('readiness')
const routingControl = createAssignmentWorkspaceResource('routingControl')
const routingToggle = createResource({ url: assignmentWorkspaceMethods.setRoutingEnabled, method: 'POST' })
const capacityUpdate = createResource({ url: assignmentWorkspaceMethods.upsertStaffCapacity, method: 'POST' })
const data = computed(() => overview.data)
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
  await Promise.all([reload(), refreshControl(), canViewReadiness.value ? readiness.fetch() : Promise.resolve()])
}

async function refreshControl() {
  await routingControl.fetch()
}

async function toggleRouting(payload) {
  controlSaving.value = true
  try {
    await routingToggle.submit(payload)
    await refreshControl()
    toast.success(payload.enabled ? __('Đã bật tự động phân công.') : __('Đã tắt tự động phân công.'))
  } catch (error) {
    toast.error(error?.messages?.[0] || __('Không thể thay đổi trạng thái routing.'))
  } finally {
    controlSaving.value = false
  }
}

async function saveCapacity(payload) {
  capacitySaving.value = true
  try {
    await capacityUpdate.submit(payload)
    await refreshControl()
    toast.success(__('Đã cập nhật capacity.'))
  } catch (error) {
    toast.error(error?.messages?.[0] || __('Không thể cập nhật capacity.'))
  } finally {
    capacitySaving.value = false
  }
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
