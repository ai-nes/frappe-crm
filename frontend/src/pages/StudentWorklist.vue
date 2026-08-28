<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs routeName="My Recommendations" :label="__('Cần liên hệ ngay')" />
    </template>
    <template #right-header>
      <Button
        variant="ghost"
        :label="__('Refresh')"
        iconLeft="refresh-cw"
        :loading="active.loading"
        @click="refresh"
      />
    </template>
  </LayoutHeader>

  <div class="flex h-full min-h-0 flex-col overflow-hidden bg-surface-white">
    <Tabs
      v-model="tabIndex"
      :tabs="workTabs"
      class="flex min-h-0 flex-1 flex-col overflow-hidden [&_[role='tab']]:px-0 [&_[role='tab']]:shrink-0 [&_[role='tablist']]:px-5 [&_[role='tablist']::-webkit-scrollbar]:h-0 [&_[role='tablist']]:min-h-[45px] [&_[role='tablist']]:gap-7.5 [&_[role='tabpanel']:not([hidden])]:flex [&_[role='tabpanel']:not([hidden])]:min-h-0 [&_[role='tabpanel']:not([hidden])]:flex-1 [&_[role='tabpanel']:not([hidden])]:flex-col [&_[role='tabpanel']:not([hidden])]:overflow-hidden"
    >
      <template #tab-panel>
        <!-- Sub-header bar -->
        <div class="border-b border-outline-gray-2 bg-surface-white px-4 py-3 sm:px-5">
          <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div class="flex items-center gap-2">
                <h1 class="text-base font-semibold text-ink-gray-9">
                  {{ queue === 'recommendations' ? __('Đề xuất liên hệ & tư vấn thí sinh') : __('Nhiệm vụ tư vấn được giao') }}
                </h1>
                <Badge
                  :label="`${active.items.length} ${queue === 'recommendations' ? __('đề xuất') : __('nhiệm vụ')}`"
                  variant="subtle"
                  theme="gray"
                  size="sm"
                />
                <Badge
                  v-if="queue === 'actions' && active.items.filter((item) => item.overdue).length"
                  :label="`${active.items.filter((item) => item.overdue).length} ${__('quá hạn SLA')}`"
                  variant="subtle"
                  theme="red"
                  size="sm"
                />
              </div>
              <p class="mt-0.5 text-xs text-ink-gray-6">
                {{ queue === 'recommendations' ? __('Ưu tiên liên hệ theo thời hạn SLA và nhu cầu đăng ký xét tuyển của thí sinh.') : __('Theo dõi và thực hiện các cuộc gọi, lịch hẹn tư vấn và chăm sóc hồ sơ theo hạn chót.') }}
              </p>
            </div>
          </div>
        </div>

        <!-- Scrollable content surface -->
        <div class="flex-1 min-h-0 overflow-y-auto bg-surface-gray-2/40 p-4 sm:p-5">
          <div
            v-if="active.loading && !active.items.length"
            class="flex min-h-60 flex-1 items-center justify-center text-ink-gray-5"
            role="status"
          >
            <LoadingIndicator class="size-6" />
            <span class="sr-only">{{ __('Đang tải danh sách...') }}</span>
          </div>

          <div
            v-else-if="active.error"
            class="flex flex-1 items-center justify-center py-8"
            role="alert"
          >
            <div class="w-full max-w-md rounded-lg border border-outline-gray-2 bg-surface-white p-5 shadow-sm">
              <p class="font-medium text-ink-gray-9">{{ __('Không thể tải danh sách') }}</p>
              <p class="mt-1 text-sm text-ink-gray-5">{{ active.error }}</p>
              <Button class="mt-4" :label="__('Thử lại')" @click="refresh" />
            </div>
          </div>

          <EmptyState
            v-else-if="!active.items.length"
            class="min-h-72 flex-1"
            name="Thí sinh"
            :icon="queue === 'recommendations' ? 'inbox' : 'check-square'"
            :title="emptyTitle"
            :description="emptyDescription"
          />

          <template v-else>
            <div class="mx-auto flex w-full max-w-4xl flex-col gap-3">
              <article
                v-for="(item, index) in active.items"
                :key="item.recommendation || item.name"
                class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 shadow-sm transition-all hover:border-outline-gray-3 hover:shadow sm:p-5"
              >
                <div class="flex flex-col gap-3">
                  <!-- Header row: badges & timing -->
                  <div class="flex items-center justify-between gap-2">
                    <div class="flex flex-wrap items-center gap-2">
                      <span class="text-xs font-medium text-ink-gray-5">#{{ index + 1 }}</span>
                      <Badge
                        v-if="queue === 'recommendations'"
                        :label="priorityLabel(item.priority)"
                        :theme="priorityTheme(item.priority)"
                        variant="subtle"
                        size="sm"
                      />
                      <Badge
                        v-else
                        :label="item.overdue ? __('Quá hạn SLA') : formatActionStatusLabel(item.status)"
                        :theme="item.overdue ? 'red' : 'gray'"
                        variant="subtle"
                        size="sm"
                      />
                    </div>
                    <div class="flex items-center gap-1 text-xs text-ink-gray-5">
                      <FeatherIcon name="clock" class="size-3.5" />
                      <span>{{ queue === 'recommendations' ? (item.timing || __('Chưa lên lịch')) : (item.dueAt || __('Chưa đặt hạn')) }}</span>
                    </div>
                  </div>

                  <!-- Content: title, student, reason -->
                  <div>
                    <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                      <h2
                        class="text-base font-semibold text-ink-gray-9 transition-colors hover:text-ink-gray-7 cursor-pointer"
                        @click="item.student && openStudent(item.student)"
                      >
                        {{ queue === 'recommendations' ? item.action : item.actionType }}
                      </h2>
                      <span class="text-sm font-medium text-ink-gray-6">· {{ item.studentName }}</span>
                    </div>

                    <p
                      v-if="item.reason"
                      class="mt-2 rounded-md border border-outline-gray-1 bg-surface-gray-2/60 p-2.5 text-sm leading-relaxed text-ink-gray-7"
                    >
                      {{ item.reason }}
                    </p>

                    <dl class="mt-3 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
                      <div>
                        <dt class="text-ink-gray-5">{{ __('Thí sinh') }}</dt>
                        <dd class="mt-0.5 font-medium text-ink-gray-8">{{ item.studentName }}</dd>
                      </div>
                      <div v-if="queue === 'actions'">
                        <dt class="text-ink-gray-5">{{ __('Tư vấn viên') }}</dt>
                        <dd class="mt-0.5 text-ink-gray-8">{{ item.assignee }}</dd>
                      </div>
                      <div v-if="item.outcome">
                        <dt class="text-ink-gray-5">{{ __('Kết quả tư vấn') }}</dt>
                        <dd class="mt-0.5 text-ink-gray-8">{{ formatOutcomeLabel(item.outcome) }}</dd>
                      </div>
                      <div v-if="item.linkedInteraction" class="sm:col-span-2">
                        <dt class="text-ink-gray-5">{{ __('Cuộc gọi / Tương tác liên quan') }}</dt>
                        <dd class="mt-0.5 text-ink-gray-8">{{ item.linkedInteraction }}</dd>
                      </div>
                    </dl>
                  </div>

                  <!-- Footer / Actions -->
                  <div class="mt-1 flex flex-wrap items-center justify-between gap-2 border-t border-outline-gray-1 pt-3">
                    <Button
                      size="sm"
                      variant="outline"
                      :label="__('Xem hồ sơ')"
                      iconLeft="user"
                      :disabled="!item.student"
                      @click="openStudent(item.student)"
                    />

                    <div v-if="queue === 'recommendations'" class="flex items-center gap-2">
                      <Button
                        v-if="item.permittedDecisions.includes('accepted')"
                        size="sm"
                        variant="solid"
                        theme="blue"
                        :label="__('Tiếp nhận & Lên lịch')"
                        iconLeft="calendar-plus"
                        @click="openDecision(item, 'accepted')"
                      />
                      <Button
                        v-if="item.permittedDecisions.includes('deferred')"
                        size="sm"
                        variant="outline"
                        theme="gray"
                        :label="__('Hẹn lại')"
                        iconLeft="clock"
                        @click="openDecision(item, 'deferred')"
                      />
                      <Button
                        v-if="item.permittedDecisions.includes('rejected')"
                        size="sm"
                        variant="ghost"
                        theme="red"
                        :label="__('Bỏ qua')"
                        iconLeft="x"
                        @click="openDecision(item, 'rejected')"
                      />
                    </div>

                    <div v-else-if="queue === 'actions' && item.permittedTransitions.length" class="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="solid"
                        theme="blue"
                        :label="__('Ghi nhận kết quả')"
                        iconLeft="check-circle"
                        @click="selectedAction = item"
                      />
                    </div>
                  </div>
                </div>
              </article>
            </div>

            <div v-if="active.nextCursor" class="flex justify-center pt-4 pb-2">
              <Button
                :label="__('Tải thêm')"
                :loading="active.loading"
                @click="loadMore"
              />
            </div>
          </template>
        </div>
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
  <ActionOutcomeDialog
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
import ActionOutcomeDialog from '@/components/StudentDecision/ActionOutcomeDialog.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import {
  recommendationItem,
  safeStudentDecisionError,
  actionItem,
  studentDecisionApi,
  formatOutcomeLabel,
  formatActionStatusLabel,
} from '@/utils/studentDecision'
import { Badge, Button, FeatherIcon, LoadingIndicator, Tabs, call, usePageMeta } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const queue = ref('recommendations')
const workTabs = computed(() => [
  { name: 'recommendations', label: __('Đề xuất liên hệ') },
  { name: 'actions', label: __('Nhiệm vụ của tôi') },
])
const tabIndex = computed({
  get: () => (queue.value === 'actions' ? 1 : 0),
  set: (value) => {
    queue.value = workTabs.value[Number(value)]?.name || 'recommendations'
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
    ? __('Không có thí sinh cần liên hệ khẩn')
    : __('Không có nhiệm vụ cần thực hiện'),
)
const emptyDescription = computed(() =>
  queue.value === 'recommendations'
    ? __('Tất cả đề xuất tư vấn và chăm sóc thí sinh đã được xử lý hoặc lên lịch.')
    : __('Bạn đã hoàn thành tất cả nhiệm vụ tư vấn và chăm sóc hồ sơ được giao.'),
)

usePageMeta(() => ({ title: __('Cần liên hệ ngay') }))

watch(
  queue,
  () => {
    if (!active.value.items.length && !active.value.loading) refresh()
  },
  { immediate: true },
)

function priorityLabel(priority) {
  if (!priority) return __('Không có độ ưu tiên')
  const map = {
    high: __('Ưu tiên cao'),
    medium: __('Ưu tiên trung bình'),
    low: __('Ưu tiên thấp'),
  }
  return map[priority] || __('Độ ưu tiên {0}', [priority])
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
    const mapper = kind === 'recommendations' ? recommendationItem : actionItem
    const nextItems = (response.items || []).map(mapper)
    state.items = cursor ? [...state.items, ...nextItems] : nextItems
    state.nextCursor = response.next_cursor || null
  } catch (err) {
    state.error = safeStudentDecisionError(err, __('Vui lòng thử lại.'))
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
