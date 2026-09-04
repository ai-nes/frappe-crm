<template>
  <section class="action-card rounded-lg border border-outline-gray-2 bg-surface-white" aria-labelledby="action-card-title">
    <div v-if="state !== 'available' && state !== 'stale'" class="border-b px-4 py-3" role="status">
      <div class="text-sm font-medium text-ink-gray-8">{{ stateTitle }}</div>
      <p class="mt-1 text-sm text-ink-gray-6">{{ stateMessage }}</p>
      <Button v-if="state === 'unavailable' || state === 'loading'" class="mt-3" :label="__('Refresh')" :loading="state === 'loading'" @click="$emit('refresh')" />
    </div>
    <div v-if="state === 'stale'" class="border-b bg-surface-amber-1 px-4 py-3" role="status">
      <div class="text-sm font-medium text-ink-gray-8">{{ __('This action may be out of date.') }}</div>
      <Button class="mt-2" :label="__('Refresh before continuing')" @click="$emit('refresh')" />
    </div>
    <template v-if="model && (state === 'available' || state === 'stale')">
      <header class="border-b px-4 py-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 id="action-card-title" class="text-lg font-semibold text-ink-gray-9">{{ model.sections.what.title }}</h2>
          <span class="text-xs text-ink-gray-5">{{ __('Revision {0}', [model.actionRevision ?? '—']) }}</span>
        </div>
        <p v-if="model.freshness.asOf" class="mt-1 text-xs text-ink-gray-5">{{ __('As of {0}', [model.freshness.asOf]) }}</p>
      </header>
      <div class="divide-y divide-outline-gray-2">
        <article v-for="key in sectionKeys" :key="key" class="px-4 py-4" :aria-labelledby="`action-${key}-title`">
          <h3 :id="`action-${key}-title`" class="text-sm font-semibold uppercase tracking-wide text-ink-gray-7">{{ model.sections[key].title }}</h3>
          <p class="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-gray-8">{{ model.sections[key].body || __('No detail provided.') }}</p>
          <div v-if="model.sections[key].evidence.length" class="mt-3">
            <div class="text-xs font-medium text-ink-gray-6">{{ __('Evidence') }}</div>
            <ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-gray-7"><li v-for="item in model.sections[key].evidence" :key="item">{{ item }}</li></ul>
          </div>
          <div v-if="model.sections[key].gaps.length" class="mt-3">
            <div class="text-xs font-medium text-ink-gray-6">{{ __('Gaps') }}</div>
            <ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-gray-7"><li v-for="item in model.sections[key].gaps" :key="item">{{ item }}</li></ul>
          </div>
          <slot :name="key" :section="model.sections[key]" />
        </article>
      </div>
      <div v-if="workbench" class="border-t px-4 py-4">
        <component :is="workbench" :section="model.sections.how" />
      </div>
      <section v-if="artifacts" class="border-t px-4 py-4" aria-labelledby="artifact-split-title">
        <h3 id="artifact-split-title" class="text-sm font-semibold uppercase tracking-wide text-ink-gray-7">{{ __('Đề xuất AI so với {0}', [taskNoun]) }}</h3>
        <div class="mt-3 grid gap-3 sm:grid-cols-2">
          <div class="rounded-md border border-outline-gray-2 bg-surface-gray-1 p-3">
            <div class="text-xs font-medium text-ink-gray-5">{{ __('Đề xuất AI (bất biến)') }}</div>
            <dl class="mt-2 space-y-1 text-sm text-ink-gray-8">
              <div v-for="[key, value] in artifactEntries(artifacts.proposal)" :key="`ai-${key}`" class="flex justify-between gap-3">
                <dt class="text-ink-gray-5">{{ key }}</dt><dd class="text-right">{{ value }}</dd>
              </div>
            </dl>
          </div>
          <div class="rounded-md border border-outline-gray-3 bg-surface-white p-3">
            <div class="text-xs font-medium text-ink-gray-5">{{ __('{0} (giá trị thực thi)', [taskNoun]) }}</div>
            <dl v-if="artifacts.task" class="mt-2 space-y-1 text-sm text-ink-gray-8">
              <div v-for="[key, value] in artifactEntries(artifacts.task)" :key="`task-${key}`" class="flex justify-between gap-3">
                <dt class="text-ink-gray-5">{{ key }}</dt>
                <dd class="text-right" :class="{ 'font-semibold text-ink-gray-9': artifacts.changedKeys.includes(key) }">{{ value }}</dd>
              </div>
            </dl>
            <p v-else class="mt-2 text-sm text-ink-gray-6">{{ __('Thao tác này không tạo NBA Task.') }}</p>
          </div>
        </div>
      </section>
      <footer v-if="model.allowedOperations.length" class="border-t px-4 py-4" aria-label="Available operations">
        <div class="mb-2 text-sm font-semibold text-ink-gray-8">{{ __('Available operations') }}</div>
        <div class="flex flex-wrap gap-2">
          <Button v-for="operation in model.allowedOperations" :key="operation.operationId" :label="operation.label" :disabled="!operation.available || operation.blocked || operation.requiresApproval" @click="$emit('operation', operation)">
            <template #prefix>{{ operation.requiresApproval ? __('Approval required') : '' }}</template>
          </Button>
        </div>
      </footer>
      <div v-else class="border-t px-4 py-4 text-sm text-ink-gray-6" role="status">{{ __('No operation is currently available.') }}</div>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { Button } from 'frappe-ui'
import { workbenchFor } from './workbenches'
import { NBA_TASK_LABEL, nbaTaskNoun } from '@/utils/actionWorkbench'

const props = defineProps({
  model: { type: Object, default: null },
  state: { type: String, default: 'unavailable' },
  // { proposal, task, changedKeys } from recommendationArtifacts(); when set the
  // card renders the immutable AI proposal and the human NBA Task side by side.
  decisionArtifacts: { type: Object, default: null },
})
defineEmits(['refresh', 'operation'])
const sectionKeys = ['what', 'why', 'how', 'goal', 'action']
const workbench = computed(() => workbenchFor(props.model))
const artifacts = computed(() => props.decisionArtifacts || null)
const taskNoun = computed(() => nbaTaskNoun(NBA_TASK_LABEL))
function artifactEntries(source) {
  return Object.entries(source || {})
    .filter(([, value]) => value !== undefined && value !== null && value !== '' && typeof value !== 'object')
    .map(([key, value]) => [key, String(value)])
}
const stateTitle = computed(() => ({ loading: __('Loading action…'), unavailable: __('Action unavailable'), blocked: __('Action blocked'), 'approval-required': __('Approval required') }[props.state] || __('Action unavailable')))
const stateMessage = computed(() => ({ loading: __('Loading the authoritative action details.'), unavailable: __('The action details could not be loaded. Refresh or return to the queue.'), blocked: __('This action cannot be continued in its current state.'), 'approval-required': __('Approval is required before this operation can be used.') }[props.state] || __('Review the action and refresh its details.')))
</script>
