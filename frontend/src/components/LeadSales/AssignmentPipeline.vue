<template>
  <section class="assignment-pipeline overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white" data-testid="assignment-pipeline">
    <header class="flex flex-wrap items-center justify-between gap-4 border-b border-outline-gray-1 px-5 py-4">
      <div>
        <h2 class="text-base font-semibold text-ink-gray-9">{{ __('Quy trình phân công tự động') }}</h2>
        <p class="mt-1 text-sm text-ink-gray-6">
          {{ __('Chọn một bước để xem cách xử lý và điều kiện phân công.') }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span class="rounded-full bg-surface-gray-2 px-3 py-1.5 text-sm text-ink-gray-7">
          {{ __('Chỉ xem') }}
        </span>
        <Button
          variant="solid"
          iconLeft="play"
          :label="__('Chạy lại luồng')"
          :loading="running"
          :disabled="loading || running"
          data-testid="run-assignment-pipeline"
          @click="runPipeline"
        />
      </div>
    </header>

    <div v-if="data" class="flex flex-wrap items-center justify-between gap-3 border-b border-emerald-100 bg-emerald-50/70 px-5 py-2.5 text-sm">
      <p class="font-medium text-emerald-800" role="status" aria-live="polite">
        {{ statusMessage }}
      </p>
      <p class="tabular-nums text-emerald-800">
        {{ progress.completed }}/{{ progress.total }} {{ __('bước hoàn tất') }}
      </p>
    </div>

    <div v-if="loading && !data" class="flex min-h-72 items-center justify-center px-5" role="status">
      <LoadingIndicator class="size-5 text-ink-gray-5" />
      <span class="sr-only">{{ __('Đang tải quy trình phân công') }}</span>
    </div>

    <div v-else-if="error" class="m-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">
      <p class="font-medium">{{ __('Không thể tải quy trình phân công') }}</p>
      <p class="mt-1">{{ errorMessage(error) }}</p>
      <Button class="mt-3" variant="subtle" :label="__('Thử lại')" @click="load" />
    </div>

    <template v-else-if="data">
      <div class="pipeline-viewport px-5 py-6">
        <div class="pipeline-grid" :class="{ 'is-running': running }">
          <template v-for="step in steps" :key="step.id">
            <article
              class="pipeline-step"
              :class="[stepClass(step), `node-${step.id}`]"
              role="button"
              tabindex="0"
              :aria-label="__('Xem chi tiết bước {0}', [step.title])"
              @click="openStep(step)"
              @keydown.enter="openStep(step)"
              @keydown.space.prevent="openStep(step)"
            >
              <div class="flex items-start gap-3">
                <span class="step-icon" aria-hidden="true">
                  <FeatherIcon :name="stepIcon(step.status)" class="size-4" />
                </span>
                <div class="min-w-0 flex-1">
                  <h3 class="text-sm font-semibold text-ink-gray-9">{{ step.title }}</h3>
                  <p class="mt-2 text-xs leading-5 text-ink-gray-6">{{ step.description }}</p>
                </div>
              </div>
              <div class="mt-3 border-t border-outline-gray-1 pt-2 text-xs text-ink-gray-7">
                <span class="font-medium">{{ step.detail }}</span>
              </div>
              <div class="mt-2 flex items-center justify-between gap-2 text-xs">
                <span class="text-ink-gray-6">
                  {{ step.metrics?.successCount || 0 }} {{ __('thành công') }} ·
                  {{ (step.metrics?.warningCount || 0) + (step.metrics?.errorCount || 0) }} {{ __('cần xử lý') }}
                </span>
                <span class="font-medium" :class="metricClass(step.status)">{{ statusLabel(step.status) }}</span>
              </div>
            </article>

          </template>

          <div
            v-for="connection in connections"
            :key="connectionKey(connection)"
            class="pipeline-connection"
            :class="connectionClass(connection)"
            aria-hidden="true"
          >
            <span v-if="connection.label">{{ connection.label }}</span>
            <FeatherIcon :name="connectionIcon(connection)" class="size-4" />
          </div>
        </div>
      </div>

      <footer class="flex flex-wrap items-center justify-between gap-3 border-t border-outline-gray-1 px-5 py-3 text-xs text-ink-gray-5">
        <span>{{ __('Sơ đồ lấy số liệu từ routing request và ownership hiện tại.') }}</span>
        <span v-if="lastRun" class="tabular-nums">
          {{ __('Lần chạy gần nhất: đã kiểm tra {0}, phân công {1}', [lastRun.checked, lastRun.assigned]) }}
        </span>
      </footer>
    </template>

    <Teleport to="body">
      <div v-if="selectedStep" class="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-labelledby="assignment-pipeline-detail-title">
        <button class="absolute inset-0 cursor-default bg-black/20" type="button" :aria-label="__('Đóng')" @click="closeStep" />
        <aside class="relative h-full w-full max-w-xl overflow-y-auto bg-surface-white shadow-xl">
          <header class="flex items-start justify-between border-b border-outline-gray-1 px-5 py-4">
            <div>
              <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ __('Chi tiết bước xử lý') }}</p>
              <h2 id="assignment-pipeline-detail-title" class="mt-1 text-lg font-semibold text-ink-gray-9">{{ selectedStep.title }}</h2>
            </div>
            <button ref="closeButton" type="button" class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md p-1.5 text-ink-gray-5 hover:bg-surface-gray-2 focus:outline-none focus:ring-2 focus:ring-outline-gray-4" :aria-label="__('Đóng')" @click="closeStep">
              <FeatherIcon name="x" class="size-5" aria-hidden="true" />
            </button>
          </header>

          <div class="space-y-5 p-5">
            <p class="text-sm leading-6 text-ink-gray-7">{{ selectedStep.detail }}</p>

            <section class="rounded-lg border border-outline-gray-2 bg-surface-gray-2/60 p-4">
              <p class="text-sm text-ink-gray-6">{{ __('Trong snapshot workspace hiện tại') }}</p>
              <p class="mt-2 text-xl font-semibold text-ink-gray-9">{{ selectedStep.metrics?.processedCount || 0 }} {{ __('hồ sơ') }}</p>
              <p class="mt-1 text-xs text-ink-gray-6">
                {{ selectedStep.metrics?.successCount || 0 }} {{ __('thành công') }} ·
                {{ (selectedStep.metrics?.warningCount || 0) + (selectedStep.metrics?.errorCount || 0) }} {{ __('cần xử lý') }}
              </p>
            </section>

            <section>
              <h3 class="text-sm font-semibold text-ink-gray-9">{{ __('Cách xử lý') }}</h3>
              <ul class="mt-3 space-y-3 text-sm text-ink-gray-7">
                <li v-for="rule in selectedStep.rules || []" :key="rule" class="flex gap-2">
                  <FeatherIcon name="check" class="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden="true" />
                  <span>{{ rule }}</span>
                </li>
              </ul>
            </section>

            <div class="flex gap-2 rounded-lg border border-blue-100 bg-blue-50/70 p-3 text-sm text-blue-900">
              <FeatherIcon name="info" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p>{{ __('Điều kiện và metrics được lấy từ snapshot workspace hiện tại.') }}</p>
            </div>

            <RouterLink class="flex min-h-11 items-center justify-center rounded-md border border-outline-gray-2 px-4 py-2 text-sm font-medium text-ink-gray-8 hover:bg-surface-gray-2" :to="{ name: 'Assignment Overview' }" @click="closeStep">
              {{ __('Xem danh sách học sinh') }}
            </RouterLink>
          </div>
        </aside>
      </div>
    </Teleport>
  </section>
</template>

<script setup>
import { Button, FeatherIcon, LoadingIndicator } from 'frappe-ui'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  getAssignmentPipelineSnapshot,
  runAssignmentPipeline,
  workflowProgress,
  workflowStepStatusClass,
} from '@/data/assignmentPipeline'

const CONNECTION_PRESENTATION = Object.freeze({
  'input-validation': { className: 'connection-input-validation', icon: 'arrow-right' },
  'validation-classification': { className: 'connection-validation-classification', icon: 'arrow-right' },
  'classification-matching': { className: 'connection-classification-matching', icon: 'corner-left-down' },
  'classification-review': { className: 'connection-classification-review', icon: 'corner-left-down' },
  'matching-review': { className: 'connection-matching-review', icon: 'corner-left-down' },
  'matching-assignment': { className: 'connection-matching-assignment', icon: 'arrow-down' },
  'review-assignment': { className: 'connection-review-assignment', icon: 'corner-right-down' },
})

const data = ref(null)
const loading = ref(false)
const running = ref(false)
const error = ref(null)
const selectedStep = ref(null)
const closeButton = ref(null)
const emit = defineEmits(['pipeline-run'])

const workflow = computed(() => data.value?.workflow || {})
const steps = computed(() => workflow.value.steps || [])
const connections = computed(() =>
  Array.isArray(workflow.value.connections) ? workflow.value.connections : [],
)
const progress = computed(() => workflowProgress(workflow.value))
const lastRun = computed(() => workflow.value.lastRun || null)
const statusMessage = computed(() => {
  if (running.value) return __('Đang chạy quy trình phân công tự động...')
  if (lastRun.value?.status === 'completed_with_errors') return __('Quy trình đã chạy xong, một số hồ sơ cần xử lý thêm')
  if (lastRun.value) return __('Đã chạy xong quy trình phân công tự động')
  return __('Đã cập nhật trạng thái quy trình phân công tự động')
})

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await getAssignmentPipelineSnapshot()
  } catch (err) {
    error.value = err
  } finally {
    loading.value = false
  }
}

async function runPipeline() {
  running.value = true
  error.value = null
  try {
    data.value = await runAssignmentPipeline({ limit: 50 })
    emit('pipeline-run', data.value)
  } catch (err) {
    error.value = err
  } finally {
    running.value = false
  }
}

function stepClass(step) {
  return workflowStepStatusClass(step.status)
}

function connectionKey(connection) {
  return `${connection.source || 'unknown'}-${connection.target || 'unknown'}`
}

function connectionClass(connection) {
  return CONNECTION_PRESENTATION[connectionKey(connection)]?.className || 'connection-unknown'
}

function connectionIcon(connection) {
  return CONNECTION_PRESENTATION[connectionKey(connection)]?.icon || 'arrow-right'
}

function stepIcon(status) {
  return { success: 'check-circle', warning: 'alert-triangle', error: 'x-circle' }[status] || 'circle'
}

function metricClass(status) {
  return { success: 'text-emerald-700', warning: 'text-orange-700', error: 'text-red-700' }[status] || 'text-ink-gray-6'
}

function statusLabel(status) {
  return { success: __('Hoàn tất'), warning: __('Cần xử lý'), error: __('Lỗi') }[status] || __('Chưa chạy')
}

function errorMessage(value) {
  return value?.messages?.join?.(' ') || value?.message || String(value || __('Lỗi không xác định'))
}

function openStep(step) {
  selectedStep.value = step
}

function closeStep() {
  selectedStep.value = null
}

function handleKeydown(event) {
  if (event.key === 'Escape' && selectedStep.value) closeStep()
}

watch(selectedStep, async (step) => {
  if (!step) return
  await nextTick()
  closeButton.value?.focus()
})

onMounted(load)
onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<style scoped>
.pipeline-viewport {
  background: rgb(248 250 252 / 0.72);
}

.pipeline-grid {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 64px minmax(180px, 1fr) 64px minmax(180px, 1fr);
  grid-template-rows: auto 64px auto 64px auto;
  align-items: center;
  gap: 0 12px;
  min-height: 460px;
  position: relative;
}

.pipeline-step {
  min-height: 154px;
  border: 1px solid rgb(203 213 225);
  border-radius: 10px;
  background: rgb(255 255 255);
  padding: 16px;
  transition: border-color 180ms ease-out, box-shadow 180ms ease-out, transform 180ms ease-out;
}

.pipeline-step:hover {
  border-color: rgb(148 163 184);
  box-shadow: 0 4px 12px rgb(15 23 42 / 0.08);
  transform: translateY(-1px);
}

.pipeline-step.is-success {
  border-color: rgb(251 146 60);
}

.pipeline-step.is-warning {
  border-color: rgb(253 186 116);
}

.pipeline-step.is-error {
  border-color: rgb(248 113 113);
}

.step-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  border-radius: 8px;
  background: rgb(241 245 249);
  color: rgb(71 85 105);
}

.is-success .step-icon {
  background: rgb(240 253 244);
  color: rgb(21 128 61);
}

.is-warning .step-icon {
  background: rgb(255 247 237);
  color: rgb(194 65 12);
}

.is-error .step-icon {
  background: rgb(254 242 242);
  color: rgb(185 28 28);
}

.node-input { grid-column: 1; grid-row: 1; }
.node-validation { grid-column: 3; grid-row: 1; }
.node-classification { grid-column: 5; grid-row: 1; }
.node-review { grid-column: 1; grid-row: 3; }
.node-matching { grid-column: 3; grid-row: 3; }
.node-assignment { grid-column: 3; grid-row: 5; }

.pipeline-connection {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: rgb(148 163 184);
  font-size: 11px;
  line-height: 1.25;
  text-align: center;
}

.connection-input-validation,
.connection-validation-classification {
  flex-direction: row;
}

.connection-classification-matching,
.connection-classification-review,
.connection-matching-review,
.connection-matching-assignment,
.connection-review-assignment {
  flex-direction: column;
}

.connection-input-validation { grid-column: 2; grid-row: 1; }
.connection-validation-classification { grid-column: 4; grid-row: 1; }

.connection-classification-review {
  position: absolute;
  left: 16%;
  top: 31%;
  color: rgb(194 65 12);
}

.connection-classification-matching {
  position: absolute;
  right: 26%;
  top: 31%;
  color: rgb(194 65 12);
}

.connection-matching-review {
  position: absolute;
  left: 27%;
  top: 56%;
  color: rgb(194 65 12);
}

.connection-matching-assignment {
  position: absolute;
  left: 50%;
  top: 76%;
  color: rgb(194 65 12);
}

.connection-review-assignment {
  position: absolute;
  left: 16%;
  top: 76%;
  color: rgb(100 116 139);
}

.connection-unknown {
  display: none;
}

.is-running .pipeline-step {
  animation: pipeline-pulse 1.2s ease-in-out infinite alternate;
}

@keyframes pipeline-pulse {
  from { box-shadow: 0 0 0 rgb(251 146 60 / 0); }
  to { box-shadow: 0 0 0 4px rgb(251 146 60 / 0.12); }
}

@media (max-width: 900px) {
  .pipeline-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: none;
    gap: 12px;
    min-height: 0;
  }

  .pipeline-step {
    grid-column: 1;
    grid-row: auto;
    min-height: 0;
  }

  .pipeline-step:not(:last-of-type)::after {
    content: '↓';
    display: block;
    margin: 12px auto -8px;
    color: rgb(148 163 184);
    text-align: center;
  }

  .pipeline-connection {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pipeline-step,
  .is-running .pipeline-step {
    animation: none;
    transition: none;
  }
}
</style>
