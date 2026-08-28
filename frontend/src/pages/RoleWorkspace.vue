<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden" data-testid="role-workspace">
    <LayoutHeader>
      <template #left-header><ViewBreadcrumbs :routeName="response.title || workspace.title || route.name" /></template>
      <template #right-header><Button :label="__('Refresh')" iconLeft="refresh-cw" :loading="loading" @click="refresh" /></template>
    </LayoutHeader>

    <WorkspaceFilters v-if="activeFilterSchema.length" v-model="filters" :filters="activeFilterSchema" @change="syncFilters" />

    <main class="min-h-0 flex-1 overflow-y-auto bg-surface-gray-1 px-3 py-4 sm:px-5" :aria-busy="loading">
      <header class="mb-4"><h1 class="text-xl font-semibold tracking-tight text-ink-gray-9">{{ response.title || workspace.title || __('Workspace') }}</h1><p v-if="response.description || workspace.description" class="mt-1 text-sm text-ink-gray-6">{{ response.description || workspace.description }}</p></header>

      <div v-if="loading && !hasData" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" role="status"><div v-for="index in 4" :key="index" class="h-28 animate-pulse rounded-lg bg-surface-white" /><span class="sr-only">{{ __('Loading workspace') }}</span></div>
      <section v-else-if="state === 'denied'" class="state-card" role="alert"><h2>{{ __('Not Permitted') }}</h2><p>{{ __('You do not have permission to view this workspace.') }}</p></section>
      <section v-else-if="state === 'unavailable'" class="state-card" role="status"><h2>{{ __('Workspace unavailable') }}</h2><p>{{ response.message || __('This workspace is not available in the current environment.') }}</p></section>
      <section v-else-if="state === 'error'" class="state-card" role="alert"><h2>{{ __('Workspace could not be loaded') }}</h2><p>{{ errorMessage }}</p><Button class="mt-4" :label="__('Try again')" @click="refresh" /></section>
      <section v-else-if="state === 'empty'" class="state-card" role="status"><h2>{{ response.emptyTitle || __('Nothing to show yet') }}</h2><p>{{ response.emptyMessage || __('Try changing filters or return when new work is available.') }}</p></section>
      <template v-else>
        <p v-if="response.stale" class="mb-3 text-xs text-ink-amber-600" role="status">{{ __('Showing the last available snapshot while newer data loads.') }}</p>
        <WorkspaceKpis :items="response.kpis" @drilldown="drillDown" />
        <div class="mt-4 grid gap-4" :class="response.sidePanel ? 'xl:grid-cols-[minmax(0,1fr)_20rem]' : ''">
          <StudentWorkTable v-if="response.students" :rows="response.students.items" :columns="response.students.columns" :title="response.students.title" :next-cursor="response.students.nextCursor" :loading="loading" :stale="response.stale" :empty-message="response.students.emptyMessage" @open="openStudent" @load-more="loadMore" />
          <AnalyticsWorkspace v-if="response.analytics" v-bind="response.analytics" />
          <ApprovalWorkspace v-if="response.approvals" v-bind="response.approvals" :on-decision="response.approvals.onDecision" @decided="refresh" @error="handleActionError" />
          <aside v-if="response.sidePanel" class="rounded-lg border border-outline-gray-2 bg-surface-white p-4"><h2 class="font-semibold text-ink-gray-9">{{ response.sidePanel.title }}</h2><p class="mt-2 text-sm text-ink-gray-6">{{ response.sidePanel.description }}</p></aside>
        </div>
      </template>
    </main>
  </div>
</template>

<script>
export function normalizeWorkspaceFilters(schema = [], query = {}) {
  return schema.reduce((filters, field) => {
    const value = query[field.key]
    const allowed = (field.options || []).map((option) => typeof option === 'object' ? option.value : option)
    if (typeof value === 'string' && value && (!allowed.length || allowed.includes(value))) filters[field.key] = value
    else if (field.default != null) filters[field.key] = field.default
    return filters
  }, {})
}

export function getWorkspaceFilterSchema(response = {}, workspace = {}) {
  return Array.isArray(response.filterSchema) && response.filterSchema.length
    ? response.filterSchema
    : workspace.filters || []
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

  for (const result of [rows, series]) {
    if (result?.contractStatus === 'unavailable' || result?.contractStatus === 'migration_required') {
      return {
        contractStatus: result.contractStatus,
        state: 'unavailable',
        message: result.explanation,
        snapshot: summary.snapshot || null,
      }
    }
  }

  const response = {
    ...summary,
    snapshot: summary.snapshot || null,
    kpis: Array.isArray(summary.kpis) ? summary.kpis : [],
  }

  if (Array.isArray(rows?.rows)) {
    response.students = {
      items: rows.rows,
      columns: Array.isArray(rows.columns) ? rows.columns : [],
      title: rows.title,
      nextCursor: rows.cursor || null,
      emptyMessage: rows.emptyMessage,
    }
  }
  if (Array.isArray(series?.series)) {
    response.analytics = {
      title: series.title,
      definition: series.definition,
      sourceUpdatedAt: series.sourceUpdatedAt,
      series: series.series,
      suppressed: series.suppressed,
      emptyMessage: series.emptyMessage,
    }
  }
  return response
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
import { Button, call, usePageMeta } from 'frappe-ui'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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

  if (summary?.contractStatus !== 'ready') return normalizeWorkspaceResponse(summary)
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
function openStudent(row) { const id = row.id || row.name || row.student; if (id) router.push({ name: 'CRM Student', params: { crmStudentId: id } }) }
function loadMore() { refresh(response.value.students?.nextCursor) }
function drillDown(item) { if (item.drilldown) router.push(item.drilldown) }
function handleActionError(error) { errorMessage.value = error?.message || __('The action could not be completed.') }
onBeforeUnmount(() => controller?.abort())
usePageMeta(() => ({ title: props.workspace.title || __('Workspace') }))
</script>

<style scoped>
.state-card { max-width: 36rem; border: 1px solid var(--outline-gray-2); border-radius: .5rem; background: var(--surface-white); padding: 1.25rem; color: var(--ink-gray-6); }
.state-card h2 { color: var(--ink-gray-9); font-weight: 600; }
.state-card p { margin-top: .5rem; font-size: .875rem; }
</style>
