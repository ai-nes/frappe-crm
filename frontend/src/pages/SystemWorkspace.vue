<template>
  <div
    class="flex h-full min-h-0 flex-col overflow-hidden"
    data-testid="system-workspace"
  >
    <LayoutHeader>
      <template #left-header>
        <ViewBreadcrumbs
          :route-name="route.name"
          :label="workspaceTitle || route.name"
        />
      </template>
      <template #right-header>
        <Button
          :label="__('Làm mới')"
          iconLeft="refresh-cw"
          :loading="workspaceLoading"
          @click="loadWorkspace"
        />
      </template>
    </LayoutHeader>

    <main
      class="min-h-0 flex-1 overflow-y-auto bg-surface-gray-1 p-4 sm:p-6"
      :aria-busy="workspaceLoading"
    >
      <div class="mx-auto max-w-7xl space-y-5">
        <header class="flex flex-col gap-1">
          <h1 class="text-xl font-bold tracking-tight text-ink-gray-9">
            {{ workspaceTitle || __('Không gian hệ thống') }}
          </h1>
          <p v-if="workspaceDescription" class="text-sm text-ink-gray-6">
            {{ workspaceDescription }}
          </p>
        </header>

        <section
          v-if="workspaceState === 'denied'"
          class="state-card"
          role="alert"
        >
          <FeatherIcon
            name="shield-off"
            class="size-8 text-red-500 mb-2 opacity-70"
          />
          <h2 class="text-base font-semibold text-ink-gray-9">
            {{ __('Không có quyền truy cập') }}
          </h2>
          <p class="text-sm text-ink-gray-6">
            {{
              workspaceMessage ||
              __('Bạn không có quyền xem không gian làm việc này.')
            }}
          </p>
        </section>

        <section
          v-else-if="workspaceState === 'unavailable'"
          class="state-card"
          role="status"
        >
          <FeatherIcon
            name="alert-circle"
            class="size-8 text-ink-gray-4 mb-2 opacity-60"
          />
          <h2 class="text-base font-semibold text-ink-gray-9">
            {{ __('Không khả dụng') }}
          </h2>
          <p class="text-sm text-ink-gray-6">
            {{
              workspaceMessage ||
              __(
                'Chế độ xem hệ thống này chưa khả dụng trong môi trường hiện tại.',
              )
            }}
          </p>
        </section>

        <section
          v-else-if="workspaceState === 'error'"
          class="state-card"
          role="alert"
        >
          <FeatherIcon
            name="alert-triangle"
            class="size-8 text-amber-500 mb-2 opacity-80"
          />
          <h2 class="text-base font-semibold text-ink-gray-9">
            {{ __('Không thể tải dữ liệu') }}
          </h2>
          <p class="text-sm text-ink-gray-6">
            {{ workspaceMessage || __('Vui lòng thử lại.') }}
          </p>
          <Button class="mt-4" :label="__('Thử lại')" @click="loadWorkspace" />
        </section>

        <div v-else-if="workspaceLoading" class="grid gap-4" role="status">
          <div
            class="h-48 animate-pulse rounded-xl border border-outline-gray-2/60 bg-surface-white"
          />
          <span class="sr-only">{{ __('Đang tải dữ liệu...') }}</span>
        </div>

        <section v-else-if="!hasContent" class="state-card" role="status">
          <FeatherIcon
            name="inbox"
            class="size-8 text-ink-gray-4 mb-2 opacity-60"
          />
          <h2 class="text-base font-semibold text-ink-gray-9">
            {{ emptyTitle || __('Chưa có dữ liệu') }}
          </h2>
          <p class="text-sm text-ink-gray-6">
            {{
              emptyMessage || __('Chưa có dữ liệu hệ thống cho chế độ xem này.')
            }}
          </p>
        </section>

        <div v-else class="grid gap-5">
          <OrganizationWorkspace
            v-if="workspaceOrganization"
            v-bind="workspaceOrganization"
          />
          <SystemStatusPanel v-if="workspaceStatus" v-bind="workspaceStatus" />
        </div>
      </div>
    </main>
  </div>
</template>

<script>
export function systemWorkspaceState(payload = {}) {
  if (
    payload.status === 401 ||
    payload.status === 403 ||
    payload.state === 'denied'
  )
    return 'denied'
  if (
    payload.available === false ||
    payload.state === 'unavailable' ||
    ['unavailable', 'migration_required'].includes(payload.contractStatus)
  )
    return 'unavailable'
  if (payload.state === 'error') return 'error'
  return 'ready'
}
</script>

<script setup>
import OrganizationWorkspace from '@/components/Workspaces/OrganizationWorkspace.vue'
import SystemStatusPanel from '@/components/Workspaces/SystemStatusPanel.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import { Button, call, FeatherIcon } from 'frappe-ui'
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
    const payload = await call(
      'crm.api.role_workspaces.get_workspace_summary',
      {
        workspace: workspace.route.workspace,
        view: workspace.route.view || workspace.defaultView,
        filters: workspace.preset || {},
      },
    )
    if (sequence === requestSequence) response.value = payload || {}
  } catch (error) {
    if (sequence === requestSequence) {
      response.value = {
        state: 'error',
        message: error?.message || __('Please try again.'),
      }
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
const workspaceDescription = computed(
  () => props.description || model.value.description,
)
const workspaceMessage = computed(
  () => props.message || model.value.explanation || model.value.message,
)
const workspaceOrganization = computed(
  () => props.organization || model.value.organization || null,
)
const workspaceStatus = computed(
  () => props.status || model.value.status || model.value.systemStatus || null,
)
const hasContent = computed(() =>
  Boolean(workspaceOrganization.value || workspaceStatus.value),
)
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
