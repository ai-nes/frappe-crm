<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden" data-testid="system-workspace">
    <LayoutHeader><template #left-header><ViewBreadcrumbs :route-name="route.name" :label="workspaceTitle || route.name" /></template></LayoutHeader>
    <main class="min-h-0 flex-1 overflow-y-auto bg-surface-gray-1 px-3 py-4 sm:px-5" :aria-busy="workspaceLoading">
      <header class="mb-4"><h1 class="text-xl font-semibold tracking-tight text-ink-gray-9">{{ workspaceTitle || __('System workspace') }}</h1><p v-if="workspaceDescription" class="mt-1 text-sm text-ink-gray-6">{{ workspaceDescription }}</p></header>
      <section v-if="workspaceState === 'denied'" class="state-card" role="alert"><h2>{{ __('Not Permitted') }}</h2><p>{{ workspaceMessage || __('You do not have permission to view this workspace.') }}</p></section>
      <section v-else-if="workspaceState === 'unavailable'" class="state-card" role="status"><h2>{{ __('Workspace unavailable') }}</h2><p>{{ workspaceMessage || __('This system view is not available in the current environment.') }}</p></section>
      <section v-else-if="workspaceState === 'error'" class="state-card" role="alert"><h2>{{ __('Workspace could not be loaded') }}</h2><p>{{ workspaceMessage || __('Please try again.') }}</p></section>
      <div v-else-if="workspaceLoading" class="grid gap-4" role="status"><div class="h-48 animate-pulse rounded-lg bg-surface-white" /><span class="sr-only">{{ __('Loading workspace') }}</span></div>
      <section v-else-if="!hasContent" class="state-card" role="status"><h2>{{ emptyTitle || __('Nothing to show yet') }}</h2><p>{{ emptyMessage || __('No system data is available for this view.') }}</p></section>
      <div v-else class="grid gap-4"><OrganizationWorkspace v-if="workspaceOrganization" v-bind="workspaceOrganization" /><SystemStatusPanel v-if="workspaceStatus" v-bind="workspaceStatus" /></div>
    </main>
  </div>
</template>

<script>
export function systemWorkspaceState(payload = {}) {
  if (payload.status === 401 || payload.status === 403 || payload.state === 'denied') return 'denied'
  if (payload.available === false || payload.state === 'unavailable' || ['unavailable', 'migration_required'].includes(payload.contractStatus)) return 'unavailable'
  if (payload.state === 'error') return 'error'
  return 'ready'
}
</script>

<script setup>
import OrganizationWorkspace from '@/components/Workspaces/OrganizationWorkspace.vue'
import SystemStatusPanel from '@/components/Workspaces/SystemStatusPanel.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import { call } from 'frappe-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const props = defineProps({
  title: String,
  description: String,
  workspace: Object,
  organization: Object,
  status: Object,
  state: String,
  available: { type: Boolean, default: undefined },
  contractStatus: String,
  message: String,
  loading: Boolean,
  emptyTitle: String,
  emptyMessage: String,
})
const route = useRoute()
const isLoading = ref(false)
const response = ref(null)
let requestSequence = 0

const loadWorkspace = async () => {
  const workspace = props.workspace
  if (!workspace?.route?.workspace) {
    response.value = props
    return
  }

  const sequence = ++requestSequence
  isLoading.value = true
  try {
    const payload = await call('crm.api.role_workspaces.get_workspace_summary', {
      workspace: workspace.route.workspace,
      view: workspace.route.view || workspace.defaultView,
      filters: workspace.preset || {},
    })
    if (sequence === requestSequence) response.value = payload || {}
  } catch (error) {
    if (sequence === requestSequence) {
      response.value = { state: 'error', message: error?.message || __('Please try again.') }
    }
  } finally {
    if (sequence === requestSequence) isLoading.value = false
  }
}

watch(() => props.workspace?.id, loadWorkspace)
onMounted(loadWorkspace)

const model = computed(() => response.value || props)
const workspaceState = computed(() => systemWorkspaceState(model.value))
const workspaceLoading = computed(() => isLoading.value || props.loading)
const workspaceTitle = computed(() => props.title || model.value.title)
const workspaceDescription = computed(() => props.description || model.value.description)
const workspaceMessage = computed(() => props.message || model.value.explanation || model.value.message)
const workspaceOrganization = computed(() => props.organization || model.value.organization || null)
const workspaceStatus = computed(() => props.status || model.value.status || model.value.systemStatus || null)
const hasContent = computed(() => Boolean(workspaceOrganization.value || workspaceStatus.value))
</script>

<style scoped>
.state-card { max-width: 36rem; border: 1px solid var(--outline-gray-2); border-radius: .5rem; background: var(--surface-white); padding: 1.25rem; color: var(--ink-gray-6); }
.state-card h2 { color: var(--ink-gray-9); font-weight: 600; }
.state-card p { margin-top: .5rem; font-size: .875rem; }
</style>
