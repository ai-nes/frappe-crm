<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs routeName="My Recommendations" />
    </template>
    <template #right-header>
      <Button
        :label="__('Refresh')"
        iconLeft="refresh-cw"
        :loading="active.loading"
        @click="refresh"
      />
    </template>
  </LayoutHeader>

  <div class="flex h-full min-h-0 flex-col overflow-hidden">
    <Tabs
      v-model="tabIndex"
      :tabs="workTabs"
      class="flex min-h-0 flex-1 flex-col overflow-hidden [&_[role='tab']]:px-0 [&_[role='tab']]:shrink-0 [&_[role='tablist']]:px-5 [&_[role='tablist']::-webkit-scrollbar]:h-0 [&_[role='tablist']]:min-h-[45px] [&_[role='tablist']]:gap-7.5 [&_[role='tabpanel']:not([hidden])]:flex [&_[role='tabpanel']:not([hidden])]:min-h-0 [&_[role='tabpanel']:not([hidden])]:flex-1 [&_[role='tabpanel']:not([hidden])]:overflow-y-auto"
    >
      <template #tab-panel>
        <section class="flex min-h-0 flex-1 flex-col px-3 pb-5 pt-3 sm:px-5">
          <div
            v-if="active.loading && !active.items.length"
            class="flex min-h-40 flex-1 items-center justify-center text-ink-gray-5"
            role="status"
          >
            <LoadingIndicator class="size-5" />
            <span class="sr-only">{{ __('Loading work') }}</span>
          </div>

          <div
            v-else-if="active.error"
            class="flex flex-1 items-center justify-center py-8"
            role="alert"
          >
            <div class="w-full max-w-md rounded border border-outline-gray-modals bg-surface-white p-5">
              <p class="font-medium text-ink-gray-9">
                {{ __('Work could not be loaded') }}
              </p>
              <p class="mt-1 text-sm text-ink-gray-5">{{ active.error }}</p>
              <Button class="mt-4" :label="__('Try again')" @click="refresh" />
            </div>
          </div>

          <EmptyState
            v-else-if="!active.items.length"
            class="min-h-64 flex-1"
            name="Work"
            icon="inbox"
            :title="emptyTitle"
            :description="emptyDescription"
          />

          <template v-else>
            <div class="flex flex-col divide-y rounded border border-outline-gray-2 bg-surface-white">
              <article
                v-for="(item, index) in active.items"
                :key="item.recommendation || item.name"
                class="p-4 transition-colors hover:bg-surface-gray-1 sm:p-5"
              >
                <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div class="min-w-0 flex-1">
                    <div class="flex flex-wrap items-center gap-2">
                      <span class="text-xs font-medium text-ink-gray-5">
                        #{{ index + 1 }}
                      </span>
                      <Badge
                        v-if="queue === 'recommendations'"
                        :label="priorityLabel(item.priority)"
                        :theme="priorityTheme(item.priority)"
                        variant="subtle"
                        size="sm"
                      />
                      <Badge
                        v-else
                        :label="item.overdue ? __('Overdue') : item.status"
                        :theme="item.overdue ? 'red' : 'gray'"
                        variant="subtle"
                        size="sm"
                      />
                    </div>

                    <template v-if="queue === 'recommendations'">
                      <div class="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <h2 class="text-base font-semibold text-ink-gray-9">
                          {{ item.action }}
                        </h2>
                        <span class="text-sm text-ink-gray-6">· {{ item.studentName }}</span>
                      </div>
                      <p
                        v-if="item.reason"
                        class="mt-1 whitespace-pre-wrap text-sm leading-6 text-ink-gray-6"
                      >
                        {{ item.reason }}
                      </p>
                      <dl class="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                        <div>
                          <dt class="text-ink-gray-5">{{ __('Student') }}</dt>
                          <dd class="mt-0.5 font-medium text-ink-gray-8">
                            {{ item.studentName }}
                          </dd>
                        </div>
                        <div>
                          <dt class="text-ink-gray-5">{{ __('Scheduled') }}</dt>
                          <dd class="mt-0.5 text-ink-gray-8">
                            {{ item.timing || __('Not scheduled') }}
                          </dd>
                        </div>
                      </dl>
                    </template>

                    <template v-else>
                      <div class="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <h2 class="text-base font-semibold text-ink-gray-9">
                          {{ item.actionType }}
                        </h2>
                        <span class="text-sm text-ink-gray-6">· {{ item.studentName }}</span>
                      </div>
                      <dl class="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                        <div>
                          <dt class="text-ink-gray-5">{{ __('Due') }}</dt>
                          <dd
                            class="mt-0.5"
                            :class="item.overdue ? 'font-medium text-red-600' : 'text-ink-gray-8'"
                          >
                            {{ item.dueAt || __('Not scheduled') }}
                          </dd>
                        </div>
                        <div>
                          <dt class="text-ink-gray-5">{{ __('Assignee') }}</dt>
                          <dd class="mt-0.5 text-ink-gray-8">{{ item.assignee }}</dd>
                        </div>
                        <div v-if="item.outcome">
                          <dt class="text-ink-gray-5">{{ __('Outcome') }}</dt>
                          <dd class="mt-0.5 text-ink-gray-8">{{ item.outcome }}</dd>
                        </div>
                      </dl>
                      <p
                        v-if="item.linkedInteraction"
                        class="mt-3 text-sm text-ink-gray-6"
                      >
                        {{ __('Linked interaction') }}: {{ item.linkedInteraction }}
                      </p>
                    </template>
                  </div>

                  <div class="flex shrink-0 flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      :label="__('Open student')"
                      :disabled="!item.student"
                      @click="openStudent(item.student)"
                    />
                    <Button
                      v-if="queue === 'actions' && item.permittedTransitions.length"
                      size="sm"
                      variant="solid"
                      :label="__('Update action')"
                      @click="selectedAction = item"
                    />
                  </div>
                </div>

                <div
                  v-if="queue === 'recommendations'"
                  class="mt-4 flex flex-wrap gap-2 border-t border-outline-gray-1 pt-3"
                >
                  <Button
                    v-if="item.permittedDecisions.includes('accepted')"
                    size="sm"
                    variant="solid"
                    theme="green"
                    :label="__('Accept')"
                    @click="openDecision(item, 'accepted')"
                  />
                  <Button
                    v-if="item.permittedDecisions.includes('deferred')"
                    size="sm"
                    variant="outline"
                    theme="gray"
                    :label="__('Defer')"
                    @click="openDecision(item, 'deferred')"
                  />
                  <Button
                    v-if="item.permittedDecisions.includes('rejected')"
                    size="sm"
                    variant="outline"
                    theme="red"
                    :label="__('Reject')"
                    @click="openDecision(item, 'rejected')"
                  />
                </div>
              </article>
            </div>

            <div v-if="active.nextCursor" class="flex justify-center pt-4">
              <Button
                :label="__('Load more')"
                :loading="active.loading"
                @click="loadMore"
              />
            </div>
          </template>
        </section>
      </template>
    </Tabs>
  </div>

  <RecommendationDecisionDialog
    v-if="selectedRecommendation"
    v-model="showDecision"
    :item="selectedRecommendation"
    :status="decisionStatus"
    @changed="handleChanged"
    @refresh-required="refresh"
  />
  <SalesActionOutcomeDialog
    v-if="selectedAction"
    v-model="showAction"
    :action="selectedAction"
    @changed="handleChanged"
    @refresh-required="refresh"
  />
</template>

<script setup>
import EmptyState from '@/components/ListViews/EmptyState.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import RecommendationDecisionDialog from '@/components/StudentDecision/RecommendationDecisionDialog.vue'
import SalesActionOutcomeDialog from '@/components/StudentDecision/SalesActionOutcomeDialog.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import {
  recommendationItem,
  safeStudentDecisionError,
  salesActionItem,
  studentDecisionApi,
} from '@/utils/studentDecision'
import { Badge, Button, LoadingIndicator, Tabs, call, usePageMeta } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const queue = ref('recommendations')
const workTabs = [
  { name: 'recommendations', label: __('Recommendation inbox') },
  { name: 'actions', label: __('My actions') },
]
const tabIndex = computed({
  get: () => (queue.value === 'actions' ? 1 : 0),
  set: (value) => {
    queue.value = workTabs[Number(value)]?.name || 'recommendations'
  },
})
const recommendations = ref({ items: [], nextCursor: null, loading: false, error: '' })
const actions = ref({ items: [], nextCursor: null, loading: false, error: '' })
const selectedRecommendation = ref(null)
const decisionStatus = ref('')
const selectedAction = ref(null)
const showDecision = computed({
  get: () => Boolean(selectedRecommendation.value),
  set: (value) => {
    if (!value) selectedRecommendation.value = null
  },
})
const showAction = computed({
  get: () => Boolean(selectedAction.value),
  set: (value) => {
    if (!value) selectedAction.value = null
  },
})
const active = computed(() =>
  queue.value === 'recommendations' ? recommendations.value : actions.value,
)
const emptyTitle = computed(() =>
  queue.value === 'recommendations'
    ? __('No recommendations to decide')
    : __('No actions assigned to you'),
)
const emptyDescription = computed(() =>
  queue.value === 'recommendations'
    ? __('New or returning recommendations will appear here.')
    : __('Your active Sales Actions will appear here.'),
)

usePageMeta(() => ({ title: __('My Recommendations') }))

watch(
  queue,
  () => {
    if (!active.value.items.length && !active.value.loading) refresh()
  },
  { immediate: true },
)

function priorityLabel(priority) {
  return priority ? __('{0} priority', [priority]) : __('Priority unavailable')
}

function priorityTheme(priority) {
  return { high: 'orange', medium: 'blue', low: 'gray' }[priority] || 'gray'
}

async function fetchPage(kind, cursor = null) {
  const state = kind === 'recommendations' ? recommendations.value : actions.value
  state.loading = true
  state.error = ''
  try {
    const response = await call(
      kind === 'recommendations'
        ? studentDecisionApi.listRecommendations
        : studentDecisionApi.listActions,
      { ...(cursor ? { cursor } : {}), page_size: 20 },
    )
    const mapper = kind === 'recommendations' ? recommendationItem : salesActionItem
    const nextItems = (response.items || []).map(mapper)
    state.items = cursor ? [...state.items, ...nextItems] : nextItems
    state.nextCursor = response.next_cursor || null
  } catch (err) {
    state.error = safeStudentDecisionError(err, __('Please try again.'))
  } finally {
    state.loading = false
  }
}

function refresh() {
  fetchPage(queue.value)
}

function loadMore() {
  if (active.value.nextCursor) fetchPage(queue.value, active.value.nextCursor)
}

function openStudent(student) {
  router.push({ name: 'CRM Student', params: { crmStudentId: student } })
}

function openDecision(item, status) {
  selectedRecommendation.value = item
  decisionStatus.value = status
}

function handleChanged() {
  refresh()
}
</script>
