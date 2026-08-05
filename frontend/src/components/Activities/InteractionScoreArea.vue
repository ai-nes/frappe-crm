<template>
  <FadedScrollableDiv class="flex h-full flex-col overflow-y-auto">
    <div class="flex flex-col gap-4 px-3 pb-5 pt-3 sm:px-10">
      <div
        v-if="loading"
        class="flex h-40 items-center justify-center text-ink-gray-5"
      >
        <LoadingIndicator class="size-5" />
      </div>

      <template v-else-if="type === 'interactions'">
        <div v-if="interactions.data?.length" class="flex flex-col divide-y">
          <div
            v-for="interaction in interactions.data"
            :key="interaction.name"
            class="flex gap-4 py-4"
          >
            <div class="mt-1 flex size-8 shrink-0 items-center justify-center rounded bg-surface-gray-2">
              <ActivityIcon class="size-4 text-ink-gray-7" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium text-ink-gray-9">
                  {{ interaction.summary || interaction.name }}
                </span>
                <Badge
                  v-if="interaction.interaction_type"
                  :label="interaction.interaction_type"
                  variant="subtle"
                />
                <Badge
                  v-if="interaction.outcome"
                  :label="interaction.outcome"
                  theme="gray"
                  variant="subtle"
                />
              </div>
              <div class="mt-1 text-sm text-ink-gray-5">
                {{ formatScoreDate(interaction.interaction_datetime) }}
              </div>
              <p
                v-if="interaction.notes"
                class="mt-2 whitespace-pre-wrap text-base text-ink-gray-7"
              >
                {{ interaction.notes }}
              </p>
            </div>
          </div>
        </div>
        <EmptyState
          v-else
          :title="__('No Interactions Found')"
          :description="__('Linked interactions will appear here.')"
          :icon="emptyIcon"
          top="30%"
        />
      </template>

      <template v-else>
        <div v-if="scoreContext.latest" class="flex flex-col gap-4">
          <div class="grid gap-4 xl:grid-cols-[20rem_minmax(0,1fr)]">
            <div class="rounded border bg-surface-white p-5">
              <div class="text-sm font-medium text-ink-gray-5">
                {{ __('Lead Score') }}
              </div>
              <div class="mt-3 flex items-end gap-3">
                <div class="text-5xl font-semibold leading-none text-ink-gray-9">
                  {{ formatNumber(scoreContext.latest.final_score) }}
                </div>
                <div class="pb-1">
                  <Badge
                    :label="scoreTier(scoreContext.latest.final_score)"
                    :theme="scoreTierTheme(scoreContext.latest.final_score)"
                    variant="subtle"
                  />
                </div>
              </div>
              <div class="mt-4 flex flex-wrap items-center gap-2">
                <Badge
                  :label="scoreChangeLabel(scoreContext.latest.score_change)"
                  :theme="scoreContext.latest.score_change >= 0 ? 'green' : 'red'"
                  variant="subtle"
                />
                <span class="text-sm text-ink-gray-5">
                  {{ formatScoreDate(scoreContext.latest.scoring_time) }}
                </span>
              </div>
              <div
                v-if="scoreContext.latest.triggered_by"
                class="mt-4 border-t pt-4 text-sm text-ink-gray-6"
              >
                <div class="mb-1 text-xs uppercase text-ink-gray-4">
                  {{ __('Triggered by') }}
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <Badge
                    :label="scoreContext.latest.triggered_by_doctype"
                    variant="subtle"
                  />
                  <span class="font-medium text-ink-gray-8">
                    {{ scoreContext.latest.triggered_by }}
                  </span>
                </div>
              </div>
            </div>

            <div class="rounded border bg-surface-white p-5">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 class="text-base font-semibold text-ink-gray-9">
                    {{ __('Score Overview') }}
                  </h3>
                  <div
                    v-if="scoreContext.template"
                    class="mt-1 text-sm text-ink-gray-5"
                  >
                    {{ scoreContext.template.template_name || scoreContext.template.name }}
                  </div>
                </div>
                <div class="flex gap-2">
                  <Badge
                    :label="`${scoreContext.histories.length} ${__('snapshots')}`"
                    variant="subtle"
                  />
                  <Badge
                    :label="`${scoreContext.intents.length} ${__('intents')}`"
                    variant="subtle"
                  />
                </div>
              </div>

              <div class="mt-5 grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
                <div class="rounded bg-surface-gray-1 p-4">
                  <div class="flex items-center justify-center">
                    <div
                      class="relative flex h-44 w-44 items-center justify-center rounded-full"
                      :style="{ background: scoreDonutGradient }"
                    >
                      <div class="flex h-28 w-28 flex-col items-center justify-center rounded-full bg-surface-white">
                        <div class="text-xs text-ink-gray-5">
                          {{ __('Total') }}
                        </div>
                        <div class="text-2xl font-semibold text-ink-gray-9">
                          {{ formatNumber(scoreContext.latest.final_score) }}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div class="mt-4 flex flex-col gap-2">
                    <div
                      v-for="segment in scoreDonutSegments"
                      :key="segment.key"
                      class="flex items-center justify-between gap-3 text-sm"
                    >
                      <div class="flex min-w-0 items-center gap-2">
                        <span
                          class="h-2.5 w-2.5 shrink-0 rounded-full"
                          :style="{ backgroundColor: segment.color }"
                        />
                        <span class="truncate text-ink-gray-8">
                          {{ segment.label }}
                        </span>
                      </div>
                      <div class="flex shrink-0 items-center gap-2">
                        <span class="text-ink-gray-5">
                          {{ segment.percent }}%
                        </span>
                        <span
                          class="w-10 text-right font-medium"
                          :class="segment.negative ? 'text-ink-red-3' : 'text-ink-gray-9'"
                        >
                          {{ segment.negative ? '-' : '' }}{{ formatNumber(segment.value) }}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="rounded bg-surface-gray-1 p-3">
                  <div class="mb-3 text-sm font-medium text-ink-gray-9">
                    {{ __('Top Signals') }}
                  </div>
                  <div v-if="topSignals.length" class="flex flex-col gap-2">
                    <div
                      v-for="signal in topSignals"
                      :key="`${signal.category}-${signal.idx}`"
                      class="flex items-start justify-between gap-3 rounded bg-surface-white px-3 py-2"
                    >
                      <div class="min-w-0">
                        <div class="truncate text-sm font-medium text-ink-gray-8">
                          {{ displayScoreSignal(signal) }}
                        </div>
                        <div class="text-xs text-ink-gray-5">
                          {{ displayScoreCategory(signal.category) }}
                        </div>
                      </div>
                      <span
                        class="shrink-0 text-sm font-semibold"
                        :class="signal.score >= 0 ? 'text-ink-green-3' : 'text-ink-red-3'"
                      >
                        {{ formatSignedNumber(signal.score) }}
                      </span>
                    </div>
                  </div>
                  <div v-else class="text-sm text-ink-gray-5">
                    {{ __('No score detail rows were recorded for this snapshot.') }}
                  </div>
                </div>
              </div>

              <div class="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                <ScoreBar
                  v-for="dimension in scoreDimensions"
                  :key="dimension.key"
                  :label="dimension.label"
                  :value="dimension.value"
                  :weight="dimension.weight"
                  :negative="dimension.negative"
                  compact
                />
              </div>
            </div>
          </div>

          <div
            v-if="scoreContext.intents?.length"
            class="rounded border bg-surface-white p-4"
          >
            <div class="mb-3 flex items-center justify-between">
              <h3 class="text-base font-semibold text-ink-gray-9">
                {{ __('Intent Summary') }}
              </h3>
              <span class="text-sm text-ink-gray-5">
                {{ scoreContext.intents.length }}
              </span>
            </div>
            <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <div
                v-for="intent in visibleIntents"
                :key="intent.name"
                class="rounded bg-surface-gray-1 p-3"
              >
                <div class="min-w-0">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="font-medium text-ink-gray-9">
                      {{ displayIntentType(intent.intent_type) }}
                    </span>
                    <Badge
                      :label="displayIntentRole(intent.intent_role)"
                      :theme="intent.intent_role === 'Dominant' ? 'orange' : 'gray'"
                      variant="subtle"
                    />
                    <Badge
                      v-if="intent.importance"
                      :label="displayImportance(intent.importance)"
                      variant="subtle"
                    />
                  </div>
                  <div
                    v-if="intent.notes"
                    class="mt-2 line-clamp-2 text-sm text-ink-gray-6"
                  >
                    {{ intent.notes }}
                  </div>
                  <div
                    v-if="intent.interaction"
                    class="mt-1 text-xs text-ink-gray-5"
                  >
                    {{ __('Interaction') }}: {{ intent.interaction }}
                  </div>
                </div>
                <div class="mt-3 flex items-center justify-between">
                  <span class="text-xs text-ink-gray-5">
                    {{ formatScoreDate(intent.modified) }}
                  </span>
                  <span class="text-sm font-medium text-ink-gray-8">
                    {{ formatPercent(intent.confidence) }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div class="rounded border bg-surface-white p-4">
            <div class="mb-3 flex items-center justify-between">
              <h3 class="text-base font-semibold text-ink-gray-9">
                {{ __('Score Breakdown') }}
              </h3>
              <span class="text-sm text-ink-gray-5">
                {{ scoreContext.latest.details?.length || 0 }}
              </span>
            </div>
            <div
              v-if="scoreBreakdown.length"
              class="flex flex-col divide-y"
            >
              <div
                v-for="group in scoreBreakdown"
                :key="group.category"
                class="py-3 first:pt-0 last:pb-0"
              >
                <div class="mb-2 flex items-center justify-between gap-3">
                  <div class="text-sm font-semibold text-ink-gray-9">
                    {{ displayScoreCategory(group.category) }}
                  </div>
                  <Badge
                    :label="formatSignedNumber(group.total)"
                    :theme="group.total >= 0 ? 'green' : 'red'"
                    variant="subtle"
                  />
                </div>
                <div class="overflow-hidden rounded border">
                  <div
                    v-for="detail in group.items"
                    :key="`${detail.rule_id || detail.signal}-${detail.idx}`"
                    class="grid gap-3 border-b bg-surface-white px-3 py-2 last:border-b-0 md:grid-cols-[minmax(0,1fr)_7rem]"
                  >
                    <div class="min-w-0">
                      <div class="font-medium text-ink-gray-8">
                        {{ displayScoreSignal(detail) }}
                      </div>
                      <div
                        v-if="detail.reason"
                        class="mt-1 text-sm text-ink-gray-6"
                      >
                        {{ displayScoreReason(detail.reason) }}
                      </div>
                      <div
                        v-if="detail.rule_id"
                        class="mt-1 text-xs text-ink-gray-5"
                      >
                        {{ detail.rule_id }}
                      </div>
                    </div>
                    <span
                      class="text-sm font-semibold md:text-right"
                      :class="detail.score >= 0 ? 'text-ink-green-3' : 'text-ink-red-3'"
                    >
                      {{ formatSignedNumber(detail.score) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="text-sm text-ink-gray-5">
              {{ __('No score detail rows were recorded for this snapshot.') }}
            </div>
          </div>

          <div class="rounded border bg-surface-white p-4">
            <h3 class="mb-3 text-base font-semibold text-ink-gray-9">
              {{ __('Score History') }}
            </h3>
            <div class="flex flex-col divide-y">
              <div
                v-for="score in scoreContext.histories"
                :key="score.name"
                class="grid gap-3 py-3 md:grid-cols-[7rem_minmax(0,1fr)_8rem]"
              >
                <div>
                  <div class="text-lg font-semibold text-ink-gray-9">
                    {{ formatNumber(score.final_score) }}
                  </div>
                  <Badge
                    :label="scoreChangeLabel(score.score_change)"
                    :theme="score.score_change >= 0 ? 'green' : 'red'"
                    variant="subtle"
                  />
                </div>
                <div class="min-w-0">
                  <div class="truncate font-medium text-ink-gray-8">
                    {{ score.score_template || score.name }}
                  </div>
                  <div class="mt-2 flex h-2 overflow-hidden rounded bg-surface-gray-2">
                    <div
                      class="bg-surface-gray-7"
                      :style="{ width: `${historySegment(score.fit_score)}%` }"
                    />
                    <div
                      class="bg-surface-gray-5"
                      :style="{ width: `${historySegment(score.engagement_score)}%` }"
                    />
                    <div
                      class="bg-surface-gray-4"
                      :style="{ width: `${historySegment(score.intent_score)}%` }"
                    />
                    <div
                      class="bg-surface-red-2"
                      :style="{ width: `${historySegment(Math.abs(score.negative_score || 0))}%` }"
                    />
                  </div>
                </div>
                <div class="text-sm text-ink-gray-5 md:text-right">
                  {{ formatScoreDate(score.scoring_time) }}
                </div>
              </div>
            </div>
          </div>
        </div>
        <EmptyState
          v-else
          :title="__('No Score History Found')"
          :description="__('Score snapshots for the linked student will appear here.')"
          :icon="emptyIcon"
          top="30%"
        />
      </template>
    </div>
  </FadedScrollableDiv>
</template>

<script setup>
import ActivityIcon from '@/components/Icons/ActivityIcon.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import FadedScrollableDiv from '@/components/FadedScrollableDiv.vue'
import { Badge, LoadingIndicator, createResource } from 'frappe-ui'
import { computed, h, watch } from 'vue'

const props = defineProps({
  contact: { type: Object, default: null },
  student: { type: Object, default: null },
  type: { type: String, default: 'interactions' },
})

const emptyIcon = h(ActivityIcon, { class: 'text-ink-gray-4' })

const interactions = createResource({
  url: 'frappe.client.get_list',
  auto: false,
})

const scores = createResource({
  url: 'crm.api.student_dashboard.get_student_score_context',
  auto: false,
})

const scoreContext = computed(() => ({
  histories: scores.data?.histories || [],
  latest: scores.data?.latest || null,
  intents: scores.data?.intents || [],
  template: scores.data?.template || null,
}))

const scoreBreakdown = computed(() => {
  let groups = new Map()
  ;(scoreContext.value.latest?.details || []).forEach((detail, idx) => {
    let category = detail.category || __('Other')
    if (!groups.has(category)) {
      groups.set(category, { category, total: 0, items: [] })
    }
    let group = groups.get(category)
    let score = Number(detail.score || 0)
    group.total += score
    group.items.push({ ...detail, idx, score })
  })
  return Array.from(groups.values())
})

const scoreDimensions = computed(() => {
  let latest = scoreContext.value.latest || {}
  let template = scoreContext.value.template || {}
  return [
    {
      key: 'fit',
      label: displayScoreCategory('Fit'),
      value: latest.fit_score,
      weight: template.fit_weight,
    },
    {
      key: 'engagement',
      label: displayScoreCategory('Engagement'),
      value: latest.engagement_score,
      weight: template.engagement_weight,
    },
    {
      key: 'intent',
      label: displayScoreCategory('Intent'),
      value: latest.intent_score,
      weight: template.intent_weight,
    },
    {
      key: 'time_decay',
      label: displayScoreCategory('Time Decay'),
      value: latest.time_decay_score,
    },
    {
      key: 'negative',
      label: displayScoreCategory('Negative'),
      value: latest.negative_score,
      negative: true,
    },
  ]
})

const scoreDonutSegments = computed(() => {
  let latest = scoreContext.value.latest || {}
  let segments = [
    {
      key: 'fit',
      label: displayScoreCategory('Fit'),
      value: Math.max(Number(latest.fit_score || 0), 0),
      color: '#2563eb',
    },
    {
      key: 'engagement',
      label: displayScoreCategory('Engagement'),
      value: Math.max(Number(latest.engagement_score || 0), 0),
      color: '#16a34a',
    },
    {
      key: 'intent',
      label: displayScoreCategory('Intent'),
      value: Math.max(Number(latest.intent_score || 0), 0),
      color: '#f59e0b',
    },
    {
      key: 'decay',
      label: displayScoreCategory('Time Decay'),
      value: Math.max(Number(latest.time_decay_score || 0), 0),
      color: '#64748b',
    },
    {
      key: 'negative',
      label: displayScoreCategory('Negative'),
      value: Math.abs(Math.min(Number(latest.negative_score || 0), 0)),
      color: '#dc2626',
      negative: true,
    },
  ]
  let total = segments.reduce((sum, segment) => sum + segment.value, 0)
  return segments.map((segment) => ({
    ...segment,
    percent: total ? Math.round((segment.value / total) * 100) : 0,
  }))
})

const scoreDonutGradient = computed(() => {
  let visibleSegments = scoreDonutSegments.value.filter((segment) => segment.value > 0)
  let total = visibleSegments.reduce((sum, segment) => sum + segment.value, 0)
  if (!total) return '#e5e7eb'

  let cursor = 0
  let stops = visibleSegments.map((segment) => {
    let start = cursor
    cursor += (segment.value / total) * 100
    return `${segment.color} ${start}% ${cursor}%`
  })
  return `conic-gradient(${stops.join(', ')})`
})

const topSignals = computed(() => {
  return (scoreContext.value.latest?.details || [])
    .map((detail, idx) => ({
      ...detail,
      idx,
      score: Number(detail.score || 0),
    }))
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    .slice(0, 5)
})

const visibleIntents = computed(() => {
  return [...scoreContext.value.intents]
    .sort((a, b) => {
      if (a.intent_role === 'Dominant' && b.intent_role !== 'Dominant') return -1
      if (a.intent_role !== 'Dominant' && b.intent_role === 'Dominant') return 1
      return Number(b.confidence || 0) - Number(a.confidence || 0)
    })
    .slice(0, 3)
})

const loading = computed(() =>
  props.type === 'interactions' ? interactions.loading : scores.loading,
)

const scoreCategoryLabels = {
  Fit: __('Hồ sơ phù hợp'),
  Engagement: __('Tương tác'),
  Intent: __('Ý định'),
  'Time Decay': __('Độ mới tương tác'),
  Negative: __('Điểm trừ'),
}

const intentRoleLabels = {
  Dominant: __('Nổi bật'),
  Support: __('Bổ trợ'),
}

const importanceLabels = {
  Medium: __('Trung bình'),
  High: __('Cao'),
  'Very High': __('Rất cao'),
}

const signalLabels = {
  'Intent: Enrollment': __('Ý định nhập học'),
  'Intent: Tuition Question': __('Quan tâm học phí'),
  'Open Day Visit': __('Tham dự Open Day'),
  'Grade 12 Student': __('Học sinh lớp 12'),
  'High GPA (>= 8.0)': __('GPA cao (>= 8.0)'),
  'Major Inquiry': __('Quan tâm ngành học'),
  'Admission Process': __('Quan tâm quy trình tuyển sinh'),
}

const reasonLabels = {
  'Verified grade 12 from academic results.': __('Đã xác nhận đang học lớp 12 từ kết quả học tập.'),
  'Transcript score 8.5 >= 8.0.': __('Điểm học bạ 8.5 >= 8.0.'),
}

function formatNumber(value) {
  let number = Number(value || 0)
  return Number.isInteger(number) ? number : number.toFixed(2)
}

function formatSignedNumber(value) {
  let number = Number(value || 0)
  let formatted = formatNumber(Math.abs(number))
  return number >= 0 ? `+${formatted}` : `-${formatted}`
}

function scoreChangeLabel(value) {
  return formatSignedNumber(value || 0)
}

function formatPercent(value) {
  if (value == null || value === '') return '0%'
  return `${formatNumber(value)}%`
}

function formatPercentWeight(value) {
  let number = Number(value || 0)
  if (number > 0 && number <= 1) {
    number *= 100
  }
  return `${formatNumber(number)}%`
}

function formatScoreDate(value) {
  if (!value) return ''
  let date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('vi-VN', {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function displayScoreCategory(value) {
  return scoreCategoryLabels[value] || __(value || 'Khác')
}

function displayIntentRole(value) {
  return intentRoleLabels[value] || __(value || '')
}

function displayImportance(value) {
  return importanceLabels[value] || __(value || '')
}

function displayIntentType(value) {
  return signalLabels[value] || __(value || '')
}

function displayScoreSignal(detail) {
  let value = detail?.signal || detail?.rule_id || ''
  return signalLabels[value] || __(value || 'Quy tắc điểm')
}

function displayScoreReason(value) {
  return reasonLabels[value] || __(value || '')
}

function scoreTier(value) {
  let score = Number(value || 0)
  if (score >= 80) return __('High Potential')
  if (score >= 50) return __('Medium Potential')
  return __('Low Potential')
}

function scoreTierTheme(value) {
  let score = Number(value || 0)
  if (score >= 80) return 'red'
  if (score >= 50) return 'orange'
  return 'gray'
}

function historySegment(value) {
  return Math.min(Math.max(Number(value || 0), 0), 100)
}

watch(
  () => [
    props.contact?.name,
    props.contact?.student,
    props.student?.name,
  ],
  () => {
    let studentName = props.student?.name || props.contact?.student
    let contactName = props.contact?.name

    if (studentName || contactName) {
      let filters = studentName
        ? { student: studentName }
        : { crm_contact: contactName }

      interactions.submit({
        doctype: 'CRM Interaction',
        fields: [
          'name',
          'interaction_type',
          'interaction_datetime',
          'outcome',
          'summary',
          'notes',
        ],
        filters,
        order_by: 'interaction_datetime desc',
        limit_page_length: 50,
      })
    } else {
      interactions.data = []
    }

    if (props.type === 'scores' && (studentName || contactName)) {
      scores.submit({
        student: studentName,
        contact: contactName,
        limit: 50,
      })
    } else {
      scores.data = null
    }
  },
  { immediate: true },
)
</script>

<script>
export default {
  components: {
    ScoreMetric: {
      props: {
        label: { type: String, required: true },
        value: { type: [Number, String], default: 0 },
      },
      template: `
        <div class="rounded bg-surface-gray-1 px-3 py-2">
          <div class="text-xs text-ink-gray-5">{{ label }}</div>
          <div class="mt-1 text-base font-medium text-ink-gray-9">{{ value || 0 }}</div>
        </div>
      `,
    },
    ScoreBar: {
      props: {
        label: { type: String, required: true },
        value: { type: [Number, String], default: 0 },
        weight: { type: [Number, String], default: null },
        negative: { type: Boolean, default: false },
        compact: { type: Boolean, default: false },
      },
      methods: {
        formatNumber(value) {
          let number = Number(value || 0)
          return Number.isInteger(number) ? number : number.toFixed(2)
        },
        formatWeight(value) {
          if (value == null || value === '') return ''
          let number = Number(value || 0)
          if (number > 0 && number <= 1) number *= 100
          return `${this.formatNumber(number)}%`
        },
        dimensionPercent(value) {
          return Math.min(Math.abs(Number(value || 0)), 100)
        },
      },
      template: `
        <div :class="compact ? 'rounded bg-surface-gray-1 p-3' : ''">
          <div class="mb-1 flex items-center justify-between gap-3">
            <div class="min-w-0 truncate text-sm font-medium text-ink-gray-8">
              {{ label }}
              <span v-if="weight != null" class="text-xs font-normal text-ink-gray-5">
                · {{ formatWeight(weight) }}
              </span>
            </div>
            <div
              class="shrink-0 text-sm font-semibold"
              :class="negative ? 'text-ink-red-3' : 'text-ink-gray-9'"
            >
              {{ negative && Number(value || 0) > 0 ? '-' : '' }}{{ formatNumber(Math.abs(Number(value || 0))) }}
            </div>
          </div>
          <div class="h-2 overflow-hidden rounded bg-surface-gray-2">
            <div
              class="h-full rounded"
              :class="negative ? 'bg-surface-red-2' : 'bg-surface-gray-7'"
              :style="{ width: dimensionPercent(value) + '%' }"
            />
          </div>
        </div>
      `,
    },
  },
}
</script>
