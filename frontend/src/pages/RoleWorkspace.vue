<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden" data-testid="role-workspace">
    <LayoutHeader>
      <template #left-header>
        <ViewBreadcrumbs :routeName="response.title || workspace.title || route.name" />
      </template>
      <template #right-header>
        <Button
          :label="__('Làm mới')"
          iconLeft="refresh-cw"
          :loading="loading"
          @click="refresh"
        />
      </template>
    </LayoutHeader>

    <WorkspaceFilters
      v-if="activeFilterSchema.length"
      v-model="filters"
      :filters="activeFilterSchema"
      @change="syncFilters"
    />

    <main
      class="min-h-0 flex-1 overflow-y-auto bg-surface-gray-1 p-4 sm:p-6"
      :aria-busy="loading"
    >
      <div class="mx-auto max-w-7xl space-y-5">
        <header class="flex flex-col gap-1">
          <h1 class="text-xl font-bold tracking-tight text-ink-gray-9">
            {{ response.title || workspace.title || __('Không gian làm việc') }}
          </h1>
          <p
            v-if="response.description || workspace.description"
            class="text-sm text-ink-gray-6"
          >
            {{ response.description || workspace.description }}
          </p>
        </header>

        <div
          v-if="loading && !hasData"
          class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
          role="status"
        >
          <div
            v-for="index in 4"
            :key="index"
            class="h-32 animate-pulse rounded-xl border border-outline-gray-2/60 bg-surface-white"
          />
          <span class="sr-only">{{ __('Đang tải dữ liệu...') }}</span>
        </div>

        <section
          v-else-if="state === 'denied'"
          class="state-card"
          role="alert"
        >
          <FeatherIcon name="shield-off" class="size-8 text-red-500 mb-2 opacity-70" />
          <h2 class="text-base font-semibold text-ink-gray-9">{{ __('Không có quyền truy cập') }}</h2>
          <p class="text-sm text-ink-gray-6">{{ __('Bạn không có quyền xem không gian làm việc này.') }}</p>
        </section>

        <section
          v-else-if="state === 'unavailable'"
          class="state-card"
          role="status"
        >
          <FeatherIcon name="alert-circle" class="size-8 text-ink-gray-4 mb-2 opacity-60" />
          <h2 class="text-base font-semibold text-ink-gray-9">{{ __('Không khả dụng') }}</h2>
          <p class="text-sm text-ink-gray-6">
            {{ response.message || __('Không gian làm việc này chưa khả dụng trong môi trường hiện tại.') }}
          </p>
        </section>

        <section
          v-else-if="state === 'error'"
          class="state-card"
          role="alert"
        >
          <FeatherIcon name="alert-triangle" class="size-8 text-amber-500 mb-2 opacity-80" />
          <h2 class="text-base font-semibold text-ink-gray-9">{{ __('Không thể tải dữ liệu') }}</h2>
          <p class="text-sm text-ink-gray-6">{{ errorMessage }}</p>
          <Button class="mt-4" :label="__('Thử lại')" @click="refresh" />
        </section>

        <section
          v-else-if="state === 'empty'"
          class="state-card"
          role="status"
        >
          <FeatherIcon name="inbox" class="size-8 text-ink-gray-4 mb-2 opacity-60" />
          <h2 class="text-base font-semibold text-ink-gray-9">{{ response.emptyTitle || __('Chưa có dữ liệu') }}</h2>
          <p class="text-sm text-ink-gray-6">
            {{ response.emptyMessage || __('Hãy thử thay đổi bộ lọc hoặc quay lại khi có dữ liệu mới.') }}
          </p>
        </section>

        <template v-else>
          <div
            v-if="response.stale"
            class="flex items-center gap-2 rounded-lg border border-amber-200/70 bg-amber-50/80 px-3.5 py-2 text-xs font-medium text-amber-900 shadow-xs"
            role="status"
          >
            <FeatherIcon name="info" class="size-4 shrink-0 text-amber-600" />
            <span>{{ __('Đang hiển thị bản chụp trước đó trong khi tải dữ liệu mới nhất.') }}</span>
          </div>

          <div
            v-if="response.partialMessage"
            class="flex items-start gap-2.5 rounded-xl border border-amber-200/80 bg-amber-50/80 p-3.5 text-sm text-amber-900 shadow-xs"
            role="status"
          >
            <FeatherIcon name="alert-triangle" class="size-4.5 shrink-0 text-amber-600 mt-0.5" />
            <span class="leading-relaxed">{{ response.partialMessage }}</span>
          </div>

          <WorkspaceKpis :items="response.kpis" @drilldown="drillDown" />

          <div
            class="grid gap-5"
            :class="response.sidePanel ? 'xl:grid-cols-[minmax(0,1fr)_20rem]' : ''"
          >
            <StudentWorkTable
              v-if="response.students"
              :rows="response.students.items"
              :columns="response.students.columns"
              :title="response.students.title"
              :next-cursor="response.students.nextCursor"
              :loading="loading"
              :stale="response.stale"
              :empty-message="response.students.emptyMessage"
              :export-action="response.exportAction"
              @open="openStudent"
              @load-more="loadMore"
              @export="exportRows"
            />
            <AnalyticsWorkspace
              v-if="response.analytics"
              v-bind="response.analytics"
            />
            <ApprovalWorkspace
              v-if="response.approvals"
              v-bind="response.approvals"
              :on-decision="response.approvals.onDecision"
              @decided="refresh"
              @error="handleActionError"
            />
            <aside
              v-if="response.sidePanel"
              class="rounded-xl border border-outline-gray-2/80 bg-surface-white p-5 shadow-xs"
            >
              <h2 class="font-semibold text-ink-gray-9">{{ response.sidePanel.title }}</h2>
              <p class="mt-2 text-sm text-ink-gray-6">{{ response.sidePanel.description }}</p>
            </aside>
          </div>
        </template>
      </div>
    </main>
  </div>
</template>

<script>
export function normalizeWorkspaceFilters(schema = [], query = {}) {
  return normalizeWorkspaceFilterSchema(schema).reduce((filters, field) => {
    const value = query[field.key]
    const allowed = (field.options || []).map((option) => typeof option === 'object' ? option.value : option)
    if (typeof value === 'string' && value && (!allowed.length || allowed.includes(value))) filters[field.key] = value
    else if (field.default != null) filters[field.key] = field.default
    return filters
  }, {})
}

export function getWorkspaceFilterSchema(response = {}, workspace = {}) {
  // The server owns the schema. It may wrap the array to include schema
  // metadata, but an `allowed` key list is not sufficient to render controls.
  if (Array.isArray(response.filterSchema)) return response.filterSchema
  const schema = response.filterSchema?.fields || response.filterSchema?.filters
  if (Array.isArray(schema)) return schema
  if (Array.isArray(response.filterSchema?.allowed)) return normalizeWorkspaceFilterSchema(response.filterSchema.allowed)
  return workspace.filters || []
}

export function normalizeWorkspaceFilterSchema(schema = []) {
  return schema.map((field) => {
    if (typeof field === 'string') return { key: field, label: filterLabel(field), options: [] }
    if (!field?.key) return null
    return { ...field, label: field.label || filterLabel(field.key), options: Array.isArray(field.options) ? field.options : [] }
  }).filter(Boolean)
}

function filterLabel(key) {
  return String(key).replace(/([A-Z])/g, ' $1').replace(/[-_]/g, ' ').replace(/^./, (letter) => letter.toUpperCase())
}

export function workspaceState(response = {}) {
  if (response.status === 401 || response.status === 403 || response.state === 'denied') return 'denied'
  if (
    response.available === false ||
    response.state === 'unavailable' ||
    response.contractStatus === 'unavailable' ||
    response.contractStatus === 'migration_required'
  ) return 'unavailable'
  if (response.state === 'empty' || response.empty === true) return 'empty'
  return 'ready'
}

export function workspaceRequest(workspace = {}, filters = {}, snapshot, cursor) {
  const route = workspace.route || {}
  if (!route.workspace) return null

  const preset = workspace.preset && typeof workspace.preset === 'object'
    ? workspace.preset
    : {}

  return {
    workspace: route.workspace,
    view: route.view || workspace.defaultView || undefined,
    // Registry presets are the initial contract; URL/schema filters are the
    // user override. Keep the merge deterministic for signed snapshots.
    filters: { ...preset, ...filters },
    ...(snapshot ? { snapshot } : {}),
    ...(cursor ? { cursor } : {}),
  }
}

export function normalizeWorkspaceResponse(summary = {}, rows, series) {
  const contractStatus = summary.contractStatus
  if (contractStatus === 'unavailable' || contractStatus === 'migration_required') {
    return {
      contractStatus,
      state: 'unavailable',
      message: summary.explanation,
      snapshot: summary.snapshot || null,
    }
  }

  const readyChannels = [rows, series].filter((result) => result?.contractStatus === 'ready')
  if (readyChannels.some((result) => !sameSnapshotMetadata(summary, result))) {
    return {
      contractStatus: 'unavailable',
      state: 'unavailable',
      message: __('The workspace data changed while it was loading. Please refresh.'),
      snapshot: null,
    }
  }

  const response = {
    ...summary,
    snapshot: summary.snapshot || null,
    kpis: Array.isArray(summary.kpis) ? summary.kpis : [],
  }

  const partialSources = [summary, rows, series].filter((result) =>
    result && (['partial', 'unavailable', 'migration_required'].includes(result.contractStatus) || result.availability?.status === 'partial'),
  )
  if (partialSources.length) {
    response.partial = true
    response.partialMessage = partialSources.map((result) => result.availability?.reason || result.explanation || __('Some workspace data is not available for this view.')).filter((message, index, messages) => messages.indexOf(message) === index).join(' ')
  }

  const rowColumns = Array.isArray(rows?.columns)
    ? rows.columns
    : Array.isArray(rows?.rowSchema)
      ? rows.rowSchema.map((field) => ({ key: field.field || field.key, label: field.label || field.field || field.key, redaction: field.redaction }))
      : []
  // Analytics-only views return an empty row channel. Do not render a misleading
  // “Students” card just because the generic facade always includes `rows: []`.
  if (Array.isArray(rows?.rows) && rowColumns.length) {
    response.students = {
      items: rows.rows,
      columns: rowColumns,
      title: rows.title,
      nextCursor: rows.cursor || null,
      emptyMessage: rows.emptyMessage,
    }
    response.exportAction = summary.exportAction || rows.exportAction || null
  }
  if (Array.isArray(series?.series)) {
    response.analytics = {
      title: series.title || summary.title,
      definition: series.definition || summary.definition,
      sourceUpdatedAt: series.sourceUpdatedAt || series.snapshotContext?.asOf || summary.snapshotContext?.asOf,
      series: series.series,
      suppressed: series.suppressed,
      emptyMessage: series.emptyMessage,
      coverage: series.availability?.coverage || summary.availability?.coverage,
    }
  }
  return response
}

export function sameSnapshotMetadata(summary = {}, result) {
  if (!result || result.contractStatus !== 'ready') return true
  if (!summary.snapshot || result.snapshot !== summary.snapshot) return false
  const expected = summary.snapshotContext || {}
  const actual = result.snapshotContext || {}
  return (!expected.definitionVersion || expected.definitionVersion === actual.definitionVersion) &&
    (!expected.timezone || expected.timezone === actual.timezone) &&
    (!expected.asOf || expected.asOf === actual.asOf)
}

export async function resolveWorkspaceDetail(target, request, navigate, context = {}) {
  if (!target?.resolver || !target?.token) return false
  const resolved = await request(target.resolver, { ...context, token: target.token })
  if (!resolved?.route) return false
  await navigate(resolved.route)
  return true
}
</script>

<script setup>
import ApprovalWorkspace from '@/components/Workspaces/ApprovalWorkspace.vue'
import AnalyticsWorkspace from '@/components/Workspaces/AnalyticsWorkspace.vue'
import StudentWorkTable from '@/components/Workspaces/StudentWorkTable.vue'
import WorkspaceFilters from '@/components/Workspaces/WorkspaceFilters.vue'
import WorkspaceKpis from '@/components/Workspaces/WorkspaceKpis.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import { Button, call, FeatherIcon } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const props = defineProps({
  workspace: { type: Object, default: () => ({}) },
  readWorkspace: Function,
})
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const errorMessage = ref('')
const response = ref({})
const filters = ref(normalizeWorkspaceFilters(props.workspace.filters, route.query))
let controller
const hasData = computed(() => Boolean(response.value.kpis?.length || response.value.students || response.value.analytics || response.value.approvals))
const state = computed(() => errorMessage.value ? 'error' : workspaceState(response.value))
const activeFilterSchema = computed(() =>
  getWorkspaceFilterSchema(response.value, props.workspace),
)

watch(() => [props.workspace, route.query], () => {
  filters.value = normalizeWorkspaceFilters(activeFilterSchema.value, route.query)
  refresh()
}, { deep: true, immediate: true })

function syncFilters(next) {
  filters.value = next
  const query = { ...route.query }
  for (const field of activeFilterSchema.value) {
    if (next[field.key]) query[field.key] = next[field.key]
    else delete query[field.key]
  }
  router.replace({ query })
}

async function refresh(cursor) {
  controller?.abort()
  const requestController = new AbortController()
  controller = requestController
  loading.value = true
  errorMessage.value = ''
  try {
    const reader = props.readWorkspace || readRoleWorkspace
    response.value = await reader({ workspace: props.workspace, filters: filters.value, cursor, signal: requestController.signal }) || { state: 'empty' }
  } catch (error) {
    if (error?.name !== 'AbortError') errorMessage.value = error?.message || __('Please try again.')
  } finally {
    if (!requestController.signal.aborted && controller === requestController) loading.value = false
  }
}

function throwIfAborted(signal) {
  if (signal?.aborted) throw new DOMException('Workspace request was aborted.', 'AbortError')
}

async function readRoleWorkspace({ workspace, filters, cursor, signal }) {
  const summaryArgs = workspaceRequest(workspace, filters)
  if (!summaryArgs) {
    return { state: 'unavailable', message: __('This workspace route is not configured.') }
  }

  // frappe-ui's call helper does not currently forward AbortSignal to fetch.
  // Keep cancellation as a stale-response guard before and after each request.
  throwIfAborted(signal)
  const summary = await call('crm.api.role_workspaces.get_workspace_summary', summaryArgs)
  throwIfAborted(signal)

  if (!['ready', 'partial'].includes(summary?.contractStatus)) return normalizeWorkspaceResponse(summary)
  if (!summary.snapshot) {
    return {
      state: 'unavailable',
      contractStatus: 'unavailable',
      message: __('The workspace reader did not provide a signed snapshot.'),
    }
  }

  const signedArgs = workspaceRequest(workspace, filters, summary.snapshot, cursor)
  const [rows, series] = await Promise.all([
    call('crm.api.role_workspaces.get_workspace_rows', signedArgs),
    call('crm.api.role_workspaces.get_workspace_series', signedArgs),
  ])
  throwIfAborted(signal)
  return normalizeWorkspaceResponse(summary, rows, series)
}
async function openStudent(row) {
  // The server alone determines whether a row can be opened. Do not build a
  // destination from arbitrary data fields; only consume its logical hand-off.
  const target = row?.drillDown
  try {
    const context = workspaceRequest(props.workspace, filters.value, response.value.snapshot)
    const navigated = await resolveWorkspaceDetail(target, call, (route) => router.push(route), context)
    if (!navigated) throw new Error(__('This record is no longer available.'))
  } catch (error) { handleActionError(error) }
}
function loadMore() { refresh(response.value.students?.nextCursor) }
function drillDown(item) { if (item?.drilldown?.route) router.push(item.drilldown.route) }
function handleActionError(error) { errorMessage.value = error?.message || __('The action could not be completed.') }
async function exportRows() {
  const exportAction = response.value.exportAction
  if (!exportAction?.token || !response.value.snapshot) return
  try {
    const result = await call('crm.api.role_workspaces.get_workspace_export', {
      ...workspaceRequest(props.workspace, filters.value, response.value.snapshot), export_id: exportAction.token,
    })
    if (!result?.download) throw new Error(result?.exportReason || __('Export is not available for this view.'))
    window.open(result.download, '_blank', 'noopener,noreferrer')
  } catch (error) { handleActionError(error) }
}
onBeforeUnmount(() => controller?.abort())
usePageMeta(() => ({ title: props.workspace.title || __('Workspace') }))
</script>

<style scoped>
.state-card {
  max-width: 28rem;
  margin: 3rem auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  border: 1px solid var(--outline-gray-2);
  border-radius: 0.75rem;
  background: var(--surface-white);
  padding: 2rem;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}
.state-card h2 {
  color: var(--ink-gray-9);
  font-weight: 600;
  margin-top: 0.5rem;
}
.state-card p {
  margin-top: 0.5rem;
  font-size: 0.875rem;
  color: var(--ink-gray-6);
}
</style>
