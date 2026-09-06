<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs
        routeName="Assignment Overview"
        :label="__('Phân bổ Lead')"
      />
    </template>
    <template #right-header>
      <Button
        variant="subtle"
        :label="__('Làm mới')"
        iconLeft="refresh-cw"
        :loading="
          overview.loading ||
          readiness.loading ||
          routingControl.loading ||
          setup.loading
        "
        @click="refresh"
      />
    </template>
  </LayoutHeader>

  <main
    class="assignment-overview h-full overflow-y-auto bg-surface-gray-2/40 p-4 sm:p-5"
  >
    <div class="mx-auto max-w-[1600px] space-y-5">
      <div
        v-if="overview.error"
        class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900"
        role="alert"
      >
        <p class="font-medium">{{ __('Không thể tải cấu hình phân bổ') }}</p>
        <p class="mt-1">{{ errorMessage(overview.error) }}</p>
        <Button class="mt-3" :label="__('Thử lại')" @click="refresh" />
      </div>

      <div
        class="assignment-workspace-tabs flex flex-col overflow-hidden rounded-xl border border-outline-gray-2 bg-surface-white shadow-sm"
      >
        <div
          role="tablist"
          :aria-label="__('Phân bổ Lead')"
          class="flex min-h-[52px] gap-6 overflow-x-auto border-b border-outline-gray-1 px-4 sm:px-5"
        >
          <button
            v-for="(tab, index) in workspaceTabs"
            :id="`assignment-tab-${tab.key}`"
            :key="tab.key"
            type="button"
            role="tab"
            :aria-selected="tabIndex === index"
            :aria-controls="`assignment-panel-${tab.key}`"
            class="shrink-0 border-b-2 border-transparent px-1 py-3 text-base text-ink-gray-5 transition hover:text-ink-gray-9 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
            :class="tabIndex === index ? 'border-ink-gray-9 text-ink-gray-9' : ''"
            @click="tabIndex = index"
          >
            {{ tab.label }}
          </button>
        </div>

        <div
          v-for="(tab, index) in workspaceTabs"
          v-show="tabIndex === index"
          :id="`assignment-panel-${tab.key}`"
          :key="`${tab.key}-panel`"
          role="tabpanel"
          :aria-labelledby="`assignment-tab-${tab.key}`"
          tabindex="0"
          class="flex flex-col overflow-auto"
        >
          <div v-if="tab.key === 'tree'" class="space-y-4 p-4 sm:p-5">
            <AssignmentOverviewFilters
              :model-value="filters"
              :schema="data?.filter_schema"
              @update:modelValue="applyFilters"
              @reset="resetFilters"
            >
              <template v-if="canManageSetup" #actions>
                <button
                  type="button"
                  data-testid="open-assignment-setup-drawer"
                  class="inline-flex min-h-9 min-w-9 items-center justify-center rounded-md text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-9 focus:outline-none focus:ring-2 focus:ring-blue-400"
                  :aria-label="__('Các bước setup')"
                  :title="__('Các bước setup')"
                  @click="setupDrawerOpen = true"
                >
                  <FeatherIcon name="help-circle" class="size-4" aria-hidden="true" />
                </button>
              </template>
            </AssignmentOverviewFilters>
            <AssignmentSetupDrawer
              v-model="setupDrawerOpen"
              :data="setup.data"
              :control="routingControl.data"
              :loading="setup.loading"
              :error="setup.error"
              :can-manage="canConfigureSystem(currentUser)"
              @refresh="refresh"
              @navigate="handleSetupNavigate"
            />
            <AssignmentOverviewTable
              :rows="normalizedRows"
              :loading="overview.loading"
              :next-cursor="nextCursor"
              :active-filter-count="activeFilterCount"
              @load-more="loadMore"
              @scope-change="loadAssignmentScope"
            />
            <p
              v-if="data?.warnings?.length"
              class="rounded-lg border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900"
            >
              <span
                v-for="warning in data.warnings"
                :key="warning.code"
                class="block"
                >{{ warning.message }}</span
              >
            </p>
          </div>

          <div v-else-if="tab.key === 'setup'" class="p-4 sm:p-5">
            <AssignmentSetupPanel
              :data="setup.data"
              :control="routingControl.data"
              :loading="setup.loading"
              :error="setup.error"
              :can-manage="canConfigureSystem(currentUser)"
              @refresh="refresh"
              @navigate="goToTab"
            />
          </div>
          <div v-else-if="tab.key === 'control'" class="p-4 sm:p-5">
            <AssignmentRoutingControlPanel
              :control="routingControl.data"
              :loading="routingControl.loading"
              :saving="controlSaving"
              :error="routingControl.error"
              :can-manage="canManageControl"
              @refresh="refreshControl"
              @toggle="toggleRouting"
              @navigate="goToTab"
            />
          </div>
          <div v-else-if="tab.key === 'load'" class="p-4 sm:p-5">
            <AssignmentLoadBalancePanel
              :staff-load="routingControl.data?.staff_load || []"
              :loading="routingControl.loading"
              :saving="capacitySaving"
              :can-manage="canManageControl"
              @refresh="refreshControl"
              @save-capacity="saveCapacity"
            />
          </div>
          <div v-else-if="tab.key === 'policy'" class="p-4 sm:p-5">
            <AssignmentPolicyPanel
              :policies="routingControl.data?.policies || []"
              :options="routingControl.data?.policy_options || {}"
              :can-manage="canManageControl"
              :can-approve="routingControl.data?.can_approve_policy"
              @changed="refreshControl"
            />
          </div>
          <div v-else class="p-4 sm:p-5">
            <SetupReadinessPanel
              v-if="canViewReadiness && readiness.data"
              :data="readiness.data"
              :loading="readiness.loading"
              @refresh="refresh"
            />
            <section
              v-else-if="canViewReadiness && readiness.error"
              class="rounded-lg border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900"
            >
              <p class="font-medium">
                {{ __('Không thể kiểm tra trạng thái tài khoản') }}
              </p>
              <p class="mt-1">{{ errorMessage(readiness.error) }}</p>
            </section>
            <section
              v-else
              class="rounded-lg border border-blue-100 bg-blue-50/70 p-4 text-sm text-blue-900"
            >
              <div class="flex gap-2">
                <FeatherIcon
                  name="info"
                  class="mt-0.5 size-4 shrink-0"
                  aria-hidden="true"
                />
                <p>
                  {{
                    __(
                      'Bạn đang xem phần phân bổ trong phạm vi Team. Phần kiểm tra User → Role → Permission Profile chỉ hiển thị cho System Manager.',
                    )
                  }}
                </p>
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { Button, FeatherIcon, createResource, toast } from 'frappe-ui'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LayoutHeader from '@/components/LayoutHeader.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import AssignmentOverviewFilters from '@/components/AssignmentWorkspace/AssignmentOverviewFilters.vue'
import AssignmentOverviewTable from '@/components/AssignmentWorkspace/AssignmentOverviewTable.vue'
import SetupReadinessPanel from '@/components/AssignmentWorkspace/SetupReadinessPanel.vue'
import AssignmentRoutingControlPanel from '@/components/AssignmentWorkspace/AssignmentRoutingControlPanel.vue'
import AssignmentLoadBalancePanel from '@/components/AssignmentWorkspace/AssignmentLoadBalancePanel.vue'
import AssignmentPolicyPanel from '@/components/AssignmentWorkspace/AssignmentPolicyPanel.vue'
import AssignmentSetupPanel from '@/components/AssignmentWorkspace/AssignmentSetupPanel.vue'
import AssignmentSetupDrawer from '@/components/AssignmentWorkspace/AssignmentSetupDrawer.vue'
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
const setupDrawerOpen = ref(false)
const controlSaving = ref(false)
const capacitySaving = ref(false)
const workspaceTabs = computed(() => [
  { key: 'tree', name: 'tree', label: __('Sơ đồ phân bổ') },
  ...(canManageSetup.value
    ? [{ key: 'setup', name: 'setup', label: __('Thiết lập') }]
    : []),
  { key: 'load', name: 'load', label: __('Giới hạn nhận') },
  { key: 'policy', name: 'policy', label: __('Cách chia Lead') },
  { key: 'readiness', name: 'readiness', label: __('Kiểm tra') },
  { key: 'control', name: 'control', label: __('Tự động') },
])

const overview = createAssignmentWorkspaceResource('overview')
const readiness = createAssignmentWorkspaceResource('readiness')
const setup = createAssignmentWorkspaceResource('setup')
const routingControl = createAssignmentWorkspaceResource('routingControl')
const routingToggle = createResource({
  url: assignmentWorkspaceMethods.setRoutingEnabled,
  method: 'POST',
})
const capacityUpdate = createResource({
  url: assignmentWorkspaceMethods.upsertStaffCapacity,
  method: 'POST',
})
const data = computed(() => overview.data)
const canManageSetup = computed(() =>
  Boolean(
    data.value?.capabilities?.can_view_readiness ||
    data.value?.capabilities?.can_edit_identity,
  ),
)
const normalizedRows = computed(() =>
  normalizeAssignmentWorkspaceRows(rows.value),
)
const nextCursor = computed(() => data.value?.next_cursor || null)
const rows = ref([])
const topologyRows = ref([])
const assignmentScope = ref(null)
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
  () =>
    Object.values(filters).filter(
      (value) =>
        value !== undefined &&
        value !== null &&
        value !== '' &&
        value !== 'all',
    ).length,
)

function requestParams(cursor, scope = assignmentScope.value) {
  const requestFilters = scope ? { ...filters, ...scope } : filters
  return {
    filters: serializeAssignmentWorkspaceFilters(requestFilters),
    limit: 100,
    cursor,
  }
}

async function reload({ append = false } = {}) {
  const result = await overview.submit(
    requestParams(append ? nextCursor.value : undefined),
  )
  const payload = result || overview.data
  const payloadRows = payload?.rows || []
  if (!assignmentScope.value) {
    rows.value = append ? [...rows.value, ...payloadRows] : payloadRows
    if (!append) topologyRows.value = payloadRows.filter((row) => row.level !== 'high_school')
    return
  }

  const scopedSchools = payloadRows.filter((row) => row.level === 'high_school')
  const scopedTopology = payloadRows.filter((row) => row.level !== 'high_school')
  const topology = append ? rows.value.filter((row) => row.level !== 'high_school') : topologyRows.value
  const topologyById = new Map(
    [...topology, ...scopedTopology].map((row) => [row.id, row]),
  )
  const existingSchools = append
    ? rows.value.filter((row) => row.level === 'high_school')
    : []
  const schoolsById = new Map(
    [...existingSchools, ...scopedSchools].map((row) => [row.id, row]),
  )
  rows.value = [...topologyById.values(), ...schoolsById.values()]
}

async function loadAssignmentScope(scope) {
  assignmentScope.value = {
    province: scope?.province || undefined,
    zone: scope?.zone || undefined,
  }
  await reload()
}

async function refresh() {
  await Promise.all([
    reload(),
    refreshControl(),
    canViewReadiness.value ? readiness.fetch() : Promise.resolve(),
  ])
  if (canManageSetup.value) await setup.fetch()
}

async function refreshControl() {
  await routingControl.fetch()
}

async function toggleRouting(payload) {
  controlSaving.value = true
  try {
    await routingToggle.submit({
      ...payload,
      reason: payload.enabled
        ? __('Bật phân công tự động từ màn hình Phân bổ Lead.')
        : __('Tắt phân công tự động từ màn hình Phân bổ Lead.'),
    })
    await refreshControl()
    toast.success(
      payload.enabled
        ? __('Đã bật tự động phân công.')
        : __('Đã tắt tự động phân công.'),
    )
  } catch (error) {
    toast.error(
      error?.messages?.[0] || __('Không thể thay đổi trạng thái routing.'),
    )
  } finally {
    controlSaving.value = false
  }
}

async function saveCapacity(payload) {
  capacitySaving.value = true
  try {
    await capacityUpdate.submit(payload)
    await refreshControl()
    toast.success(__('Đã cập nhật giới hạn Lead.'))
  } catch (error) {
    toast.error(
      error?.messages?.[0] || __('Không thể cập nhật giới hạn Lead.'),
    )
  } finally {
    capacitySaving.value = false
  }
}

async function applyFilters(next) {
  for (const key of Object.keys(filters)) {
    if (!(key in next)) delete filters[key]
  }
  Object.assign(filters, next)
  assignmentScope.value = null
  await router.replace({ query: assignmentWorkspaceFilterQuery(filters) })
  await reload()
}

async function resetFilters() {
  for (const key of Object.keys(filters)) delete filters[key]
  assignmentScope.value = null
  await router.replace({ query: {} })
  await reload()
}

async function loadMore() {
  if (nextCursor.value) await reload({ append: true })
}

function goToTab(key) {
  const index = workspaceTabs.value.findIndex((tab) => tab.key === key)
  if (index >= 0) tabIndex.value = index
}

function handleSetupNavigate(tab) {
  setupDrawerOpen.value = false
  goToTab(tab)
}

function errorMessage(error) {
  return (
    error?.messages?.join?.(' ') ||
    error?.message ||
    String(error || __('Lỗi không xác định'))
  )
}

onMounted(refresh)
</script>

<style scoped>
.assignment-overview {
  min-height: calc(100vh - 7rem);
}
</style>
