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
                {{ formatDate(interaction.interaction_datetime) }}
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
          :description="__('Interactions linked to this student will appear here.')"
          :icon="emptyIcon"
          top="30%"
        />
      </template>

      <template v-else>
        <div v-if="scores.data?.length" class="flex flex-col gap-4">
          <div
            v-for="score in scores.data"
            :key="score.name"
            class="rounded border bg-surface-white p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div class="flex items-center gap-2">
                  <span class="text-lg font-semibold text-ink-gray-9">
                    {{ score.final_score }}
                  </span>
                  <Badge
                    :label="score.score_change >= 0 ? `+${score.score_change || 0}` : score.score_change"
                    :theme="score.score_change >= 0 ? 'green' : 'red'"
                    variant="subtle"
                  />
                </div>
                <div class="mt-1 text-sm text-ink-gray-5">
                  {{ formatDate(score.scoring_time) }}
                </div>
              </div>
              <Badge
                v-if="score.score_template"
                :label="score.score_template"
                variant="subtle"
              />
            </div>

            <div class="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
              <ScoreMetric :label="__('Fit')" :value="score.fit_score" />
              <ScoreMetric
                :label="__('Engagement')"
                :value="score.engagement_score"
              />
              <ScoreMetric :label="__('Intent')" :value="score.intent_score" />
              <ScoreMetric
                :label="__('Time Decay')"
                :value="score.time_decay_score"
              />
              <ScoreMetric
                :label="__('Negative')"
                :value="score.negative_score"
              />
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
import { formatDate } from '@/utils'
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
  url: 'frappe.client.get_list',
  auto: false,
})

const loading = computed(() =>
  props.type === 'interactions' ? interactions.loading : scores.loading,
)

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

    if (props.type === 'scores' && studentName) {
      scores.submit({
        doctype: 'CRM Score History',
        fields: [
          'name',
          'score_template',
          'scoring_time',
          'fit_score',
          'engagement_score',
          'intent_score',
          'time_decay_score',
          'negative_score',
          'final_score',
          'score_change',
        ],
        filters: { student: studentName },
        order_by: 'scoring_time desc, creation desc',
        limit_page_length: 50,
      })
    } else {
      scores.data = []
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
  },
}
</script>
