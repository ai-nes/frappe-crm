<template>
  <div class="actions-workbench flex h-full min-h-0 flex-col overflow-y-auto">
    <header class="actions-hero border-b border-outline-gray-2 px-5 pb-5 pt-5 sm:px-6">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div class="min-w-0">
          <div class="text-xs font-semibold tracking-[0.08em] text-ink-gray-5">{{ __('WORK QUEUE') }}</div>
          <h3 class="mt-2 text-2xl font-semibold tracking-tight text-ink-gray-9">{{ __('Action workspace') }}</h3>
          <p class="mt-1 max-w-2xl text-sm leading-6 text-ink-gray-6">{{ __('See what needs attention, what is due today, and what has been completed.') }}</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button :label="__('Refresh')" icon-left="refresh-cw" :loading="actions.loading" @click="actions.reload()" />
          <Button :label="__('Open worklist')" @click="router.push({ name: 'My Recommendations' })" />
          <Button variant="solid" :label="__('Add Action')" @click="openCreate" />
        </div>
      </div>
      <div class="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-outline-gray-2 bg-outline-gray-2 sm:grid-cols-4">
        <div v-for="metric in metrics" :key="metric.label" class="bg-surface-white px-3 py-3 sm:px-4">
          <div class="text-xs text-ink-gray-5">{{ metric.label }}</div>
          <div class="mt-1 text-xl font-semibold tabular-nums text-ink-gray-9">{{ metric.value }}</div>
        </div>
      </div>
    </header>

    <div class="flex flex-col gap-3 border-b border-outline-gray-2 px-5 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div class="flex min-w-0 gap-1 rounded-lg bg-surface-gray-2 p-1" role="tablist" :aria-label="__('Action filters')">
        <button v-for="filter in filters" :key="filter.value" type="button" class="actions-filter min-h-10 rounded-md px-3 text-sm font-medium text-ink-gray-6" :class="{ 'actions-filter-active': activeFilter === filter.value }" :aria-selected="activeFilter === filter.value" role="tab" @click="activeFilter = filter.value">
          {{ filter.label }} <span class="ml-1 tabular-nums text-xs">{{ filter.count }}</span>
        </button>
      </div>
      <span class="text-xs text-ink-gray-5">{{ __('Sorted by due date') }}</span>
    </div>

    <main class="min-h-0 flex-1 px-5 py-5 sm:px-6">
      <ErrorMessage v-if="actions.error" :message="actions.error" />
      <div v-else-if="actions.loading" class="flex justify-center py-12"><LoadingIndicator /></div>
      <div v-else-if="!filteredItems.length" class="actions-empty rounded-lg border border-dashed border-outline-gray-3 px-6 py-12 text-center">
        <div class="mx-auto flex size-12 items-center justify-center rounded-lg bg-surface-gray-2 text-ink-gray-6"><FeatherIcon name="check-circle" class="size-6" /></div>
        <h4 class="mt-4 text-base font-semibold text-ink-gray-9">{{ emptyTitle }}</h4>
        <p class="mx-auto mt-1 max-w-sm text-sm leading-6 text-ink-gray-6">{{ emptyDescription }}</p>
        <Button v-if="activeFilter !== 'all'" class="mt-4" :label="__('Show all actions')" @click="activeFilter = 'all'" />
      </div>
      <div v-else class="space-y-3">
        <article v-for="item in filteredItems" :key="item.name" class="actions-row rounded-lg border border-outline-gray-2 bg-surface-white p-4 sm:p-5">
          <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-xs font-semibold tracking-[0.06em] text-ink-gray-5">{{ item.action || item.action_type || __('Monitor') }}</span>
                <Badge :label="stateLabel(item)" :theme="stateTheme(item)" variant="subtle" />
                <Badge :label="item.origin" theme="gray" variant="subtle" />
              </div>
              <h4 class="mt-2 text-base font-semibold leading-6 text-ink-gray-9">{{ item.objective }}</h4>
              <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-gray-6">
                <span v-if="item.due_at" class="inline-flex items-center gap-1.5" :class="{ 'font-medium text-red-600': item.is_overdue }"><FeatherIcon name="calendar" class="size-4" /> {{ formatDue(item.due_at) }}</span>
                <span class="inline-flex items-center gap-1.5"><FeatherIcon name="flag" class="size-4" /> {{ priorityLabel(item.priority) }}</span>
                <span v-if="item.action_owner" class="inline-flex items-center gap-1.5"><FeatherIcon name="user" class="size-4" /> {{ item.action_owner }}</span>
              </div>
              <div v-if="item.outcome" class="mt-4 rounded-md bg-surface-gray-2 px-3 py-2 text-sm text-ink-gray-7"><span class="font-medium text-ink-gray-8">{{ __(item.outcome) }}</span><span v-if="item.outcome_evidence"> · {{ item.outcome_evidence }}</span></div>
            </div>
            <Button :label="__('Open details')" variant="subtle" @click="$emit('open-action', item.action_id || item.action || item.name)" />
          </div>
        </article>
      </div>
    </main>
  </div>

  <Dialog v-model="showCreate" :options="{ title: __('Add Action') }">
    <template #body-content>
      <div class="space-y-4 p-4">
        <ErrorMessage v-if="actionTypeCatalog.error || (!actionTypeCatalog.loading && !actionTypes.length)" :message="__('CRM Action catalog is unavailable. Ask an administrator to migrate the CRM Action catalog.')" />
        <div class="grid gap-3 sm:grid-cols-2"><Select v-model="form.action_type" :options="actionTypes" :label="__('Action type')" /><Select v-model="form.priority" :options="priorities" :label="__('Priority')" /></div>
        <FormControl v-model="form.objective" :label="__('Objective')" :placeholder="__('What needs to be done?')" />
        <FormControl v-model="form.due_at" type="datetime-local" :label="__('Due date')" :description="__('Optional. Add a deadline when this action needs a clear finish time.')" />
      </div>
    </template>
    <template #actions><Button variant="solid" :loading="creating" :disabled="!form.objective.trim() || !actionTypes.length" :label="__('Create')" @click="createAction" /></template>
  </Dialog>
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage, FeatherIcon, FormControl, LoadingIndicator, Select, call, createResource, toast } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({ doctype: { type: String, required: true }, name: { type: String, required: true }, student: { type: String, default: '' } })
defineEmits(['open-action'])
const router = useRouter()
const showCreate = ref(false)
const creating = ref(false)
const activeFilter = ref('all')
const priorities = ['high', 'medium', 'low'].map((value) => ({ label: __(value.charAt(0).toUpperCase() + value.slice(1)), value }))
const form = ref({ action_type: 'CALL', objective: '', due_at: '', priority: 'medium' })
const idempotencyKey = ref('')
const actions = createResource({ url: 'crm.api.student_worklist.list_actions_for_record', params: { doctype: props.doctype, name: props.name, page_size: 50 }, auto: true })
const actionTypeCatalog = createResource({
  url: 'frappe.client.get_list',
  params: {
    doctype: 'CRM Action',
    fields: ['code', 'display_name', 'action_type'],
    filters: { enabled: 1 },
    order_by: 'sort_order asc',
    limit_page_length: 0,
  },
  auto: true,
})
const actionTypes = computed(() => {
  const rows = Array.isArray(actionTypeCatalog.data) ? actionTypeCatalog.data : []
  return rows.map((row) => ({ label: `${row.display_name} (${row.code})`, value: row.code }))
})
const allItems = computed(() => actions.data?.items || [])
const filters = computed(() => [
  { label: __('All'), value: 'all', count: allItems.value.length },
  { label: __('Today'), value: 'today', count: allItems.value.filter((item) => item.is_today).length },
  { label: __('Overdue'), value: 'overdue', count: allItems.value.filter((item) => item.is_overdue).length },
  { label: __('Completed'), value: 'completed', count: allItems.value.filter((item) => item.state === 'completed').length },
])
const filteredItems = computed(() => activeFilter.value === 'all' ? allItems.value : allItems.value.filter((item) => activeFilter.value === 'today' ? item.is_today : activeFilter.value === 'overdue' ? item.is_overdue : item.state === 'completed'))
const metrics = computed(() => [
  { label: __('Open'), value: allItems.value.filter((item) => !['completed', 'cancelled', 'rejected', 'superseded'].includes(item.state)).length },
  { label: __('Due today'), value: allItems.value.filter((item) => item.is_today).length },
  { label: __('Overdue'), value: allItems.value.filter((item) => item.is_overdue).length },
  { label: __('Completed'), value: allItems.value.filter((item) => item.state === 'completed').length },
])
const emptyTitle = computed(() => activeFilter.value === 'all' ? __('No actions yet') : __('Nothing in this view'))
const emptyDescription = computed(() => activeFilter.value === 'all' ? __('Create an action here or accept a recommendation to start a work item.') : __('Try another filter or create a new action.'))
function openCreate() { idempotencyKey.value = globalThis.crypto?.randomUUID?.() || `${props.name}-${Date.now()}`; showCreate.value = true }
function stateLabel(item) { return item.is_overdue ? __('Overdue') : __(item.state || 'pending') }
function stateTheme(item) { if (item.is_overdue) return 'red'; if (item.state === 'completed') return 'green'; if (item.state === 'cancelled') return 'gray'; return 'blue' }
function priorityLabel(value) { return __(value ? value.charAt(0).toUpperCase() + value.slice(1) : 'Medium') }
function formatDue(value) { return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
async function createAction() {
  if (!form.value.objective.trim()) return
  creating.value = true
  try {
    await call('crm.api.student_decision.create_action', { student: props.student || props.name, contact: props.doctype === 'CRM Contact' ? props.name : null, ...form.value, due_at: form.value.due_at || null, idempotency_key: idempotencyKey.value })
    showCreate.value = false
    form.value = { action_type: 'CALL', objective: '', due_at: '', priority: 'medium' }
    actions.reload()
    toast.success(__('Action created'))
  } catch (error) { toast.error(error?.messages?.[0] || __('Unable to create Action')) } finally { creating.value = false }
}
</script>

<style scoped>
.actions-workbench { --action-accent: oklch(0.68 0.16 55); --action-ink: oklch(0.27 0.025 255); --action-surface: oklch(0.985 0.008 250); --action-line: oklch(0.88 0.018 250); --action-hero-start: oklch(0.985 0.008 250); --action-hero-end: oklch(0.965 0.018 70); background: var(--action-surface); }
.actions-hero { background: linear-gradient(135deg, var(--action-hero-start), var(--action-hero-end)); }
.actions-filter { transition: background-color 180ms ease-out, color 180ms ease-out, transform 120ms ease-out; }
.actions-filter:hover { color: var(--action-ink); transform: translateY(-1px); }
.actions-filter:active { transform: translateY(1px); }
.actions-filter:focus-visible { outline: 2px solid var(--action-accent); outline-offset: 2px; }
.actions-filter-active { background: var(--action-ink); color: oklch(0.98 0.01 250); }
.actions-row { border-color: var(--action-line); transition: transform 180ms ease-out, box-shadow 180ms ease-out; }
.actions-row:hover { transform: translateY(-1px); box-shadow: 0 8px 20px oklch(0.27 0.025 255 / 0.08); }
@media (prefers-reduced-motion: reduce) { .actions-filter, .actions-row { transition: none; } .actions-filter:hover, .actions-filter:active, .actions-row:hover { transform: none; } }
</style>
