<template>
  <section
    class="flex h-full min-h-0 w-full flex-col bg-surface-gray-1"
    aria-label="Student 360"
    data-testid="student-360-dashboard"
  >
    <header class="flex shrink-0 flex-col gap-3 border-b bg-surface-white px-5 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-6">
      <div class="min-w-0">
        <div class="text-xs font-semibold tracking-[0.08em] text-ink-gray-5">{{ __('Toàn cảnh hồ sơ tuyển sinh') }}</div>
        <div class="mt-1 flex flex-wrap items-center gap-2">
          <h2 class="text-xl font-semibold tracking-tight text-ink-gray-9">{{ __('Toàn cảnh hồ sơ tuyển sinh') }}</h2>
          <Badge :label="snapshotStatus.label" :theme="snapshotStatus.theme" variant="subtle" />
          <Badge :label="analysisStatus.label" :theme="analysisStatus.theme" variant="subtle" />
        </div>
        <p class="mt-1 max-w-3xl text-sm leading-6 text-ink-gray-6">
          {{ __('Tóm tắt tình hình để Sales nắm bối cảnh; nhật ký tương tác và điểm số luôn đọc trực tiếp từ CRM.') }}
        </p>
        <p v-if="dashboard.analyzed_at" class="mt-1 text-xs text-ink-gray-5">
          {{ __('Bản tóm tắt gần nhất:') }} {{ formatDate(dashboard.analyzed_at) }}
        </p>
      </div>
      <Button
        variant="outline"
        icon-left="refresh-cw"
        :label="refreshing ? __('Đang làm mới…') : __('Làm mới')"
        :loading="refreshing"
        :disabled="loading || refreshing"
        @click="refreshDashboard"
      />
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
      <div class="mx-auto flex max-w-6xl flex-col gap-4">
        <div v-if="error" class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {{ error }}
        </div>

        <div v-if="dashboard.snapshot_status === 'STALE'" class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {{ __('Dữ liệu CRM đã thay đổi. Bản tóm tắt này chỉ là bản tham khảo cũ; bấm “Làm mới” để yêu cầu phân tích mới.') }}
        </div>

        <div v-if="loading && !hasSnapshot" class="rounded-lg border border-outline-gray-2 bg-surface-white px-4 py-8 text-center text-sm text-ink-gray-5">
          {{ __('Đang tải toàn cảnh hồ sơ…') }}
        </div>

        <template v-else>
          <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 sm:p-5" aria-labelledby="student-360-advisory-title">
            <div class="flex items-start justify-between gap-3">
              <div>
                <h3 id="student-360-advisory-title" class="text-base font-semibold text-ink-gray-9">{{ __('Tín hiệu tư vấn tuyển sinh') }}</h3>
                <p class="mt-1 text-sm text-ink-gray-5">{{ __('Các nhận định ngắn gọn có căn cứ từ dữ liệu tuyển sinh liên quan.') }}</p>
              </div>
              <span class="text-xs tabular-nums text-ink-gray-5">{{ dashboard.advisory_signals.length }}/5</span>
            </div>
            <div v-if="dashboard.advisory_signals.length" class="mt-4 grid gap-3 lg:grid-cols-3">
              <article v-for="item in dashboard.advisory_signals" :key="findingKey(item)" class="rounded-md border border-outline-gray-2 bg-surface-gray-1 p-4">
                <div class="flex items-start justify-between gap-2">
                  <h4 class="text-sm font-semibold leading-5 text-ink-gray-9">{{ item.title }}</h4>
                  <Badge v-if="item.confidence" :label="confidenceLabel(item.confidence)" :theme="confidenceTheme(item.confidence)" variant="subtle" />
                </div>
                <p class="mt-2 text-sm leading-6 text-ink-gray-7">{{ item.summary }}</p>
                <EvidenceRefs :refs="item.evidence_refs" />
              </article>
            </div>
            <EmptyState v-else :text="__('Chưa có bản tóm tắt khả dụng.')" />
          </section>

          <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 sm:p-5" aria-labelledby="student-360-score-title">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 id="student-360-score-title" class="text-base font-semibold text-ink-gray-9">{{ __('Điểm từ CRM live') }}</h3>
                <p class="mt-1 text-sm text-ink-gray-5">{{ __('Chỉ đọc từ hệ thống chấm điểm của CRM; không tự tính hoặc điều chỉnh.') }}</p>
              </div>
            </div>
            <div class="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div v-for="metric in scoreMetrics" :key="metric.key" class="rounded-md border border-outline-gray-2 px-3 py-3">
                <div class="text-xs font-medium text-ink-gray-5">{{ metric.label }}</div>
                <div class="mt-1 text-2xl font-semibold tabular-nums text-ink-gray-9">{{ formatScore(metric.value) }}</div>
              </div>
            </div>
            <div class="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm text-ink-gray-6">
              <span v-if="dashboard.score_overview.band">{{ __('Mức điểm') }}: <strong class="font-medium text-ink-gray-8">{{ bandLabel(dashboard.score_overview.band) }}</strong></span>
              <span v-if="dashboard.score_overview.trend?.direction && dashboard.score_overview.trend.direction !== 'UNKNOWN'">{{ __('Xu hướng') }}: <strong class="font-medium text-ink-gray-8">{{ trendLabel(dashboard.score_overview.trend.direction) }}</strong><span v-if="dashboard.score_overview.trend.delta !== null && dashboard.score_overview.trend.delta !== undefined" class="ml-1 tabular-nums">({{ formatSignedScore(dashboard.score_overview.trend.delta) }})</span></span>
            </div>
            <div v-if="dashboard.score_overview.contributors?.length" class="mt-4 border-t border-outline-gray-2 pt-4">
              <h4 class="text-xs font-semibold uppercase tracking-wide text-ink-gray-5">{{ __('Tín hiệu đóng góp gần nhất') }}</h4>
              <div class="mt-2 flex flex-wrap gap-2">
                <span v-for="(contributor, index) in dashboard.score_overview.contributors" :key="`${contributor.signal || contributor.category || 'signal'}-${index}`" class="rounded-full bg-surface-gray-2 px-3 py-1 text-xs text-ink-gray-7">
                  {{ contributor.signal || contributor.category || __('Tín hiệu') }}<span v-if="contributor.score !== null && contributor.score !== undefined" class="ml-1 tabular-nums">({{ formatSignedScore(contributor.score) }})</span>
                </span>
              </div>
            </div>
          </section>

          <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 sm:p-5" aria-labelledby="student-360-journal-title">
            <div class="flex items-start justify-between gap-3">
              <div>
                <h3 id="student-360-journal-title" class="text-base font-semibold text-ink-gray-9">{{ __('Nhật ký tương tác') }}</h3>
                <p class="mt-1 text-sm text-ink-gray-5">{{ __('Dữ liệu Inbound/Outbound mới nhất đọc trực tiếp từ CRM.') }}</p>
              </div>
              <span v-if="dashboard.interaction_journal.as_of" class="text-xs text-ink-gray-5">{{ formatDate(dashboard.interaction_journal.as_of) }}</span>
            </div>
            <div class="mt-4 grid gap-4 lg:grid-cols-2">
              <div v-for="column in journalColumns" :key="column.key" class="min-w-0">
                <div class="flex items-center gap-2 border-b border-outline-gray-2 pb-2">
                  <span class="text-sm font-semibold text-ink-gray-8">{{ column.label }}</span>
                  <span class="text-xs tabular-nums text-ink-gray-5">{{ (dashboard.interaction_journal[column.key] || []).length }}</span>
                </div>
                <div v-if="dashboard.interaction_journal[column.key]?.length" class="mt-2 divide-y divide-outline-gray-2">
                  <article v-for="item in dashboard.interaction_journal[column.key]" :key="item.id" class="py-3 first:pt-1">
                    <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-gray-5">
                      <span>{{ formatDate(item.occurred_at) }}</span>
                      <span v-if="item.channel">· {{ channelLabel(item.channel) }}</span>
                      <span v-if="item.actor?.label">· {{ item.actor.label }}</span>
                    </div>
                    <p class="mt-1 text-sm leading-6 text-ink-gray-8">{{ item.summary || __('Tương tác chưa có mô tả.') }}</p>
                    <p v-if="item.outcome" class="mt-1 text-xs text-ink-gray-5">{{ __('Kết quả') }}: {{ outcomeLabel(item.outcome) }}</p>
                  </article>
                </div>
                <EmptyState
                  v-else
                  :text="column.key === 'inbound' ? __('Chưa có tương tác vào.') : __('Chưa có tương tác ra.')"
                  compact
                />
              </div>
            </div>
          </section>

          <div class="grid gap-4 lg:grid-cols-2">
            <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 sm:p-5" aria-labelledby="student-360-risk-title">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <h3 id="student-360-risk-title" class="text-base font-semibold text-ink-gray-9">{{ __('Rào cản tuyển sinh') }}</h3>
                  <p class="mt-1 text-sm text-ink-gray-5">{{ __('Những điểm có thể làm chậm tiến trình hồ sơ.') }}</p>
                </div>
                <span class="text-xs tabular-nums text-ink-gray-5">{{ dashboard.risks.length }}/3</span>
              </div>
              <div v-if="dashboard.risks.length" class="mt-4 space-y-3">
                <article v-for="item in dashboard.risks" :key="findingKey(item)" class="rounded-md border border-amber-200 bg-amber-50/60 p-4">
                  <div class="flex items-start justify-between gap-2">
                    <h4 class="text-sm font-semibold leading-5 text-ink-gray-9">{{ item.title }}</h4>
                    <Badge v-if="item.severity" :label="severityLabel(item.severity)" theme="orange" variant="subtle" />
                  </div>
                  <p class="mt-2 text-sm leading-6 text-ink-gray-7">{{ item.summary }}</p>
                  <EvidenceRefs :refs="item.evidence_refs" />
                </article>
              </div>
              <EmptyState v-else :text="__('Chưa có rào cản được bản tóm tắt ghi nhận.')" />
            </section>

            <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 sm:p-5" aria-labelledby="student-360-opportunity-title">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <h3 id="student-360-opportunity-title" class="text-base font-semibold text-ink-gray-9">{{ __('Tín hiệu thuận lợi') }}</h3>
                  <p class="mt-1 text-sm text-ink-gray-5">{{ __('Các tín hiệu tích cực có căn cứ trong hành trình tuyển sinh.') }}</p>
                </div>
                <span class="text-xs tabular-nums text-ink-gray-5">{{ dashboard.opportunity_signals.length }}/3</span>
              </div>
              <div v-if="dashboard.opportunity_signals.length" class="mt-4 space-y-3">
                <article v-for="item in dashboard.opportunity_signals" :key="findingKey(item)" class="rounded-md border border-emerald-200 bg-emerald-50/60 p-4">
                  <div class="flex items-start justify-between gap-2">
                    <h4 class="text-sm font-semibold leading-5 text-ink-gray-9">{{ item.title }}</h4>
                    <Badge v-if="item.strength" :label="strengthLabel(item.strength)" theme="green" variant="subtle" />
                  </div>
                  <p class="mt-2 text-sm leading-6 text-ink-gray-7">{{ item.summary }}</p>
                  <EvidenceRefs :refs="item.evidence_refs" />
                </article>
              </div>
              <EmptyState v-else :text="__('Chưa có tín hiệu thuận lợi được bản tóm tắt ghi nhận.')" />
            </section>
          </div>

          <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 sm:p-5" aria-labelledby="student-360-recent-title">
            <div>
              <h3 id="student-360-recent-title" class="text-base font-semibold text-ink-gray-9">{{ __('Cập nhật gần đây') }}</h3>
              <p class="mt-1 text-sm text-ink-gray-5">{{ __('Thông tin bổ trợ để bắt kịp thay đổi; không thay thế các tín hiệu chính.') }}</p>
            </div>
            <div v-if="dashboard.recent_changes.length" class="mt-4 grid gap-3 md:grid-cols-3">
              <article v-for="item in dashboard.recent_changes" :key="findingKey(item)" class="rounded-md border border-outline-gray-2 px-4 py-3">
                <div class="text-xs font-medium text-ink-gray-5">{{ changeTypeLabel(item.type) }}</div>
                <p class="mt-1 text-sm leading-6 text-ink-gray-7">{{ item.summary }}</p>
                <EvidenceRefs :refs="item.evidence_refs" />
              </article>
            </div>
            <EmptyState v-else :text="__('Chưa có cập nhật bổ trợ.')" compact />
          </section>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup>
import { Badge, Button, call } from 'frappe-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  student: { type: String, required: true },
})

const emptyDashboard = () => ({
  student_id: props.student,
  snapshot_schema_version: 'student-360-snapshot-v1',
  snapshot_status: 'NONE',
  analysis_status: 'IDLE',
  analyzed_at: null,
  advisory_signals: [],
  interaction_journal: { as_of: null, inbound: [], outbound: [] },
  score_overview: { fit: null, interaction: null, intent: null, total: null, band: null, trend: { direction: 'UNKNOWN', delta: null }, summary: '', contributors: [] },
  risks: [],
  opportunity_signals: [],
  recent_changes: [],
})

const dashboard = ref(emptyDashboard())
const loading = ref(false)
const refreshing = ref(false)
const error = ref('')
let pollTimer = null

const hasSnapshot = computed(() => dashboard.value.advisory_signals.length > 0)
const snapshotStatus = computed(() => ({
  label: { FRESH: __('Bản tóm tắt mới nhất'), STALE: __('Bản tóm tắt đã cũ'), NONE: __('Chưa có bản tóm tắt') }[dashboard.value.snapshot_status] || __('Bản tóm tắt chưa xác định'),
  theme: { FRESH: 'green', STALE: 'orange', NONE: 'gray' }[dashboard.value.snapshot_status] || 'gray',
}))
const analysisStatus = computed(() => ({
  label: { ANALYZING: __('Đang phân tích'), FAILED: __('Phân tích không thành công'), IDLE: __('Sẵn sàng') }[dashboard.value.analysis_status] || __('Chưa xác định'),
  theme: { ANALYZING: 'blue', FAILED: 'red', IDLE: 'gray' }[dashboard.value.analysis_status] || 'gray',
}))
const scoreMetrics = computed(() => [
  { key: 'fit', label: 'Fit', value: dashboard.value.score_overview.fit },
  { key: 'interaction', label: 'Interaction', value: dashboard.value.score_overview.interaction },
  { key: 'intent', label: 'Intent', value: dashboard.value.score_overview.intent },
  { key: 'total', label: 'Total', value: dashboard.value.score_overview.total },
])
const journalColumns = [
  { key: 'inbound', label: 'Inbound' },
  { key: 'outbound', label: 'Outbound' },
]

function normalizeResponse(response) {
  const payload = response?.message && typeof response.message === 'object' ? response.message : response
  const next = payload && typeof payload === 'object' ? payload : {}
  return {
    ...emptyDashboard(),
    ...next,
    advisory_signals: Array.isArray(next.advisory_signals) ? next.advisory_signals : [],
    risks: Array.isArray(next.risks) ? next.risks : [],
    opportunity_signals: Array.isArray(next.opportunity_signals) ? next.opportunity_signals : [],
    recent_changes: Array.isArray(next.recent_changes) ? next.recent_changes : [],
    interaction_journal: { ...emptyDashboard().interaction_journal, ...(next.interaction_journal || {}) },
    score_overview: { ...emptyDashboard().score_overview, ...(next.score_overview || {}) },
  }
}

async function load({ request = false, refresh = false } = {}) {
  if (!props.student) return
  clearPoll()
  loading.value = !hasSnapshot.value
  refreshing.value = refresh
  error.value = ''
  try {
    const response = await call('crm.api.analysis_run_read.get_student_360', {
      student: props.student,
      request,
      refresh,
    })
    dashboard.value = normalizeResponse(response)
  } catch {
    error.value = __('Không thể tải toàn cảnh hồ sơ. Vui lòng thử lại.')
  } finally {
    loading.value = false
    refreshing.value = false
    schedulePoll()
  }
}

function refreshDashboard() {
  load({ request: true, refresh: true })
}

function schedulePoll() {
  clearPoll()
  if (dashboard.value.analysis_status === 'ANALYZING') {
    pollTimer = window.setTimeout(() => load(), 2500)
  }
}

function clearPoll() {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = null
}

function findingKey(item) {
  return `${item.type || item.code || 'finding'}-${item.title || item.summary}`
}

function formatDate(value) {
  if (!value) return __('Chưa có thời điểm')
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function formatScore(value) {
  if (value === null || value === undefined || value === '') return '—'
  return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 }).format(Number(value))
}

function formatSignedScore(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return `${number > 0 ? '+' : ''}${formatScore(number)}`
}

function bandLabel(value) {
  return { LOW: __('Thấp'), MEDIUM: __('Trung bình'), HIGH: __('Cao'), low: __('Thấp'), medium: __('Trung bình'), high: __('Cao'), cold: __('Thấp'), warm: __('Trung bình'), hot: __('Cao') }[value] || value
}

function trendLabel(value) {
  return { UP: __('Tăng'), DOWN: __('Giảm'), FLAT: __('Ổn định') }[value] || value
}

function confidenceLabel(value) {
  return { LOW: __('Thấp'), MEDIUM: __('Trung bình'), HIGH: __('Cao') }[value] || value
}

function confidenceTheme(value) {
  return { LOW: 'gray', MEDIUM: 'orange', HIGH: 'green' }[value] || 'gray'
}

function severityLabel(value) {
  return { LOW: __('Thấp'), MEDIUM: __('Trung bình'), HIGH: __('Cao') }[value] || value
}

function strengthLabel(value) {
  return { LOW: __('Thấp'), MEDIUM: __('Trung bình'), HIGH: __('Cao') }[value] || value
}

function channelLabel(value) {
  return {
    phone: __('Điện thoại'),
    email: __('Email'),
    chat: __('Trò chuyện'),
    meeting: __('Gặp mặt'),
    social: __('Mạng xã hội'),
  }[String(value).toLowerCase()] || value
}

function outcomeLabel(value) {
  return {
    positive: __('Tích cực'),
    neutral: __('Trung tính'),
    negative: __('Chưa thuận lợi'),
    completed: __('Đã hoàn tất'),
  }[String(value).toLowerCase()] || value
}

function changeTypeLabel(value) {
  return {
    lifecycle: __('Vòng đời hồ sơ'),
    application: __('Hồ sơ đăng ký'),
    interaction: __('Tương tác'),
    score: __('Điểm'),
  }[String(value).toLowerCase()] || value
}

onMounted(() => load({ request: true }))
onBeforeUnmount(clearPoll)
watch(() => props.student, () => load({ request: true }))
</script>

<script>
export default {
  components: {
    EvidenceRefs: {
      props: { refs: { type: Array, default: () => [] } },
      template: '<div v-if="refs.length" class="mt-3 flex flex-wrap gap-1" aria-label="Nguồn tham chiếu"><span v-for="ref in refs" :key="ref" class="rounded bg-surface-gray-2 px-2 py-0.5 font-mono text-[10px] text-ink-gray-5">{{ ref }}</span></div>',
    },
    EmptyState: {
      props: { text: { type: String, required: true }, compact: { type: Boolean, default: false } },
      template: '<p class="rounded-md border border-dashed border-outline-gray-2 text-sm text-ink-gray-5" :class="compact ? \'mt-3 px-3 py-3\' : \'mt-4 px-4 py-5\'">{{ text }}</p>',
    },
  },
}
</script>
