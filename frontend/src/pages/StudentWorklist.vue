<template>
  <LayoutHeader>
    <template #left-header>
      <div class="flex min-w-0 flex-col">
        <h1 class="text-lg font-semibold text-ink-gray-9">
          {{ __('My recommendations') }}
        </h1>
        <p class="text-sm text-ink-gray-5">
          {{ __('Ordered by the current recommendation policy.') }}
        </p>
      </div>
    </template>
    <template #right-header>
      <Button
        :label="__('Refresh')"
        iconLeft="refresh-cw"
        :loading="loading"
        @click="refresh"
      />
    </template>
  </LayoutHeader>

  <main
    class="h-full overflow-y-auto bg-surface-gray-1 px-3 py-4 sm:px-10 sm:py-6"
  >
    <div class="mx-auto max-w-5xl">
      <div v-if="pendingAction" class="mb-4 rounded border border-outline-gray-modals bg-surface-white p-4">
        <p class="font-medium text-ink-gray-9">{{ __('Record outcome for') }} {{ pendingAction.action_type }}</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <select v-model="selectedOutcome" class="rounded border border-outline-gray-modals px-2 py-1 text-sm">
            <option value="">{{ __('Select outcome') }}</option>
            <option v-for="outcome in outcomes" :key="outcome" :value="outcome">{{ outcome }}</option>
          </select>
          <Button size="sm" :label="__('Save outcome')" :loading="savingOutcome" :disabled="!selectedOutcome" @click="recordOutcome" />
          <Button size="sm" :label="__('Later')" theme="gray" @click="pendingAction = null" />
        </div>
      </div>
      <div
        v-if="loading && !items.length"
        class="flex min-h-48 items-center justify-center text-ink-gray-5"
      >
        <LoadingIndicator class="size-5" />
      </div>
      <div
        v-else-if="errorMessage"
        class="rounded border border-outline-gray-modals bg-surface-white p-5"
        role="alert"
      >
        <p class="font-medium text-ink-gray-9">
          {{ __('Recommendations could not be loaded') }}
        </p>
        <p class="mt-1 text-sm text-ink-gray-5">{{ errorMessage }}</p>
        <Button class="mt-4" :label="__('Try again')" @click="refresh" />
      </div>
      <div
        v-else-if="!items.length"
        class="rounded border border-dashed border-outline-gray-modals bg-surface-white px-5 py-12 text-center"
      >
        <h2 class="text-base font-semibold text-ink-gray-9">
          {{ __('No active recommendations') }}
        </h2>
        <p class="mt-1 text-sm text-ink-gray-5">
          {{ __('New recommendations will appear here when available.') }}
        </p>
      </div>
      <div v-else class="flex flex-col gap-3">
        <article
          v-for="(item, index) in items"
          :key="item.recommendation"
          class="rounded border border-outline-gray-modals bg-surface-white p-4 sm:p-5"
        >
          <div
            class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"
          >
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-sm font-medium tabular-nums text-ink-gray-5"
                  >#{{ index + 1 }}</span
                >
                <Badge
                  :label="priorityLabel(item.priority)"
                  :theme="priorityTheme(item.priority)"
                  variant="subtle"
                />
                <Badge
                  v-if="item.timing"
                  :label="item.timing"
                  theme="gray"
                  variant="subtle"
                />
              </div>
              <h2 class="mt-3 text-base font-semibold text-ink-gray-9">
                {{ item.action }}
              </h2>
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
                    {{ item.student }}
                  </dd>
                </div>
                <div>
                  <dt class="text-ink-gray-5">{{ __('Revision') }}</dt>
                  <dd class="mt-0.5 font-medium tabular-nums text-ink-gray-8">
                    {{ item.revision }}
                  </dd>
                </div>
              </dl>
            </div>
            <Button
              class="shrink-0"
              :label="__('Open student')"
              iconRight="arrow-up-right"
              @click="openStudent(item.student)"
            />
          </div>
          <div class="mt-4 flex flex-wrap gap-2 border-t border-outline-gray-1 pt-3">
            <Button size="sm" :label="__('Accept')" theme="green" :loading="deciding === item.recommendation" @click="decide(item, 'accepted')" />
            <Button size="sm" :label="__('Defer')" theme="gray" :loading="deciding === item.recommendation" @click="decide(item, 'deferred')" />
            <Button size="sm" :label="__('Reject')" theme="red" :loading="deciding === item.recommendation" @click="decide(item, 'rejected')" />
          </div>
        </article>
        <div v-if="nextCursor" class="flex justify-center pt-2">
          <Button
            :label="__('Load more')"
            :loading="loading"
            @click="loadMore"
          />
        </div>
      </div>
    </div>
  </main>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import { Badge, Button, call, LoadingIndicator, usePageMeta } from 'frappe-ui'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const items = ref([])
const nextCursor = ref(null)
const loading = ref(false)
const errorMessage = ref('')
const deciding = ref('')
const pendingAction = ref(null)
const selectedOutcome = ref('')
const savingOutcome = ref(false)
const outcomes = ['NO_RESPONSE', 'INTEREST_INCREASED', 'NEEDS_MORE_INFORMATION', 'CALL_BACK_LATER', 'APPLICATION_STARTED', 'APPLICATION_COMPLETED', 'NOT_INTERESTED']

usePageMeta(() => ({ title: __('My recommendations') }))

async function fetchPage(cursor = null) {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await call(
      'crm.api.student_worklist.list_student_worklist',
      {
        ...(cursor ? { cursor } : {}),
        page_size: 20,
      },
    )
    items.value = cursor
      ? [...items.value, ...(response.items || [])]
      : response.items || []
    nextCursor.value = response.next_cursor || null
  } catch (error) {
    errorMessage.value = error.messages?.[0] || __('Please try again.')
  } finally {
    loading.value = false
  }
}

function refresh() {
  fetchPage()
}
function loadMore() {
  if (nextCursor.value) fetchPage(nextCursor.value)
}
function openStudent(student) {
  router.push({ name: 'CRM Student', params: { crmStudentId: student } })
}
async function decide(item, status) {
  let decisionReason = null
  if (status === 'rejected' || status === 'deferred') {
    decisionReason = window.prompt(__('Please provide a reason for this decision.'))
    if (!decisionReason?.trim()) return
  }
  deciding.value = item.recommendation
  errorMessage.value = ''
  try {
    const result = await call('crm.api.student_decision.transition_recommendation', {
      name: item.recommendation,
      expected_revision: item.revision,
      status,
      decision_reason: decisionReason,
    })
    if (result.sales_action) {
      pendingAction.value = await call('crm.api.student_decision.get_sales_action', { name: result.sales_action })
    }
    // The record no longer belongs to this active worklist. Reload rather
    // than mutating local state so a concurrent server-side change is shown.
    await fetchPage()
  } catch (error) {
    errorMessage.value = error.messages?.[0] || __('This recommendation changed. Refresh and try again.')
  } finally {
    deciding.value = ''
  }
}
async function recordOutcome() {
  if (!pendingAction.value || !selectedOutcome.value) return
  savingOutcome.value = true
  try {
    await call('crm.api.student_decision.record_sales_action_outcome', {
      name: pendingAction.value.name,
      expected_revision: pendingAction.value.source_revision,
      business_outcome: selectedOutcome.value,
    })
    pendingAction.value = null
    selectedOutcome.value = ''
  } catch (error) {
    errorMessage.value = error.messages?.[0] || __('This Sales Action changed. Refresh and try again.')
  } finally {
    savingOutcome.value = false
  }
}
function priorityLabel(priority) {
  return __(
    priority
      ? `${priority.charAt(0).toUpperCase()}${priority.slice(1)} priority`
      : 'Priority unavailable',
  )
}
function priorityTheme(priority) {
  return priority === 'high' ? 'red' : priority === 'medium' ? 'orange' : 'gray'
}

refresh()
</script>
