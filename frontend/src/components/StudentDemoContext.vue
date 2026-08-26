<template>
  <section
    class="rounded-lg border border-outline-gray-2 bg-surface-white p-4"
    aria-labelledby="student-admissions-context"
  >
    <div class="mb-4">
      <h2 id="student-admissions-context" class="text-base font-semibold text-ink-gray-9">
        {{ __('Admissions context') }}
      </h2>
      <p class="mt-1 text-sm text-ink-gray-5">
        {{ __('Campaign, event and scholarship signals for the next conversation.') }}
      </p>
    </div>

    <p v-if="loading" role="status" class="text-sm text-ink-gray-5">
      {{ __('Loading admissions context…') }}
    </p>
    <p v-else-if="!context?.hasContent" class="text-sm text-ink-gray-5">
      {{ __('No campaign, event, scholarship, or next-action context is available yet.') }}
    </p>
    <dl v-else class="grid gap-4 sm:grid-cols-2">
      <div v-if="context.campaign" class="break-words">
        <dt class="text-sm text-ink-gray-5">{{ __('Campaign') }}</dt>
        <dd class="mt-1 text-sm text-ink-gray-8">
          <span class="font-medium">{{ context.campaign.label }}</span>
          <span v-if="context.campaign.source" class="text-ink-gray-5"> · {{ __(context.campaign.source) }}</span>
          <time
            v-if="context.campaign.occurredAt.label"
            :datetime="context.campaign.occurredAt.iso"
            class="mt-1 block text-ink-gray-5"
          >
            {{ context.campaign.occurredAt.label }}
          </time>
        </dd>
      </div>
      <div v-if="context.event" class="break-words">
        <dt class="text-sm text-ink-gray-5">{{ __('Open Day / event') }}</dt>
        <dd class="mt-1 text-sm text-ink-gray-8">
          <span class="font-medium">{{ context.event.label }}</span>
          <Badge
            v-if="context.event.status"
            class="ml-2"
            :label="eventStatusLabel(context.event.status)"
            :theme="eventTheme"
            variant="subtle"
          />
          <time
            v-if="context.event.occurredAt.label"
            :datetime="context.event.occurredAt.iso"
            class="mt-1 block text-ink-gray-5"
          >
            {{ context.event.occurredAt.label }}
          </time>
        </dd>
      </div>
      <div v-if="context.scholarship" class="break-words">
        <dt class="text-sm text-ink-gray-5">{{ __('Scholarship interest') }}</dt>
        <dd class="mt-1 text-sm text-ink-gray-8">
          <span class="font-medium">{{ context.scholarship.label }}</span>
          <span v-if="context.scholarship.notes" class="block">{{ context.scholarship.notes }}</span>
          <span v-if="scholarshipMeta" class="mt-1 block text-ink-gray-5">{{ scholarshipMeta }}</span>
        </dd>
      </div>
      <div v-if="context.nextAction" class="break-words sm:col-span-2">
        <dt class="text-sm text-ink-gray-5">{{ __('Next best action') }}</dt>
        <dd class="mt-1 text-sm text-ink-gray-8">
          {{ context.nextAction.summary }}
          <time
            v-if="context.nextAction.dueAt.label"
            :datetime="context.nextAction.dueAt.iso"
            class="mt-1 block text-ink-gray-5"
          >
            {{ context.nextAction.dueAt.label }}
          </time>
        </dd>
      </div>
      <div v-if="context.score" class="break-words sm:col-span-2 border-t border-outline-gray-2 pt-3">
        <dt class="text-sm text-ink-gray-5">{{ __('Potential score freshness') }}</dt>
        <dd class="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-gray-8">
          <span v-if="context.score.latest !== null">{{ __('Latest score: {0}', [context.score.latest]) }}</span>
          <Badge
            :label="context.score.state === 'current' ? __('Up to date') : context.score.state === 'pending' ? __('Recalculation pending') : __('Not calculated yet')"
            :theme="context.score.state === 'current' ? 'green' : context.score.state === 'pending' ? 'orange' : 'gray'"
            variant="subtle"
          />
        </dd>
      </div>
    </dl>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { Badge } from 'frappe-ui'

const props = defineProps({
  context: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})

const eventTheme = computed(() => {
  if (props.context?.event?.status === 'checked-in') return 'green'
  if (['invited', 'registered'].includes(props.context?.event?.status)) return 'blue'
  return 'gray'
})

const scholarshipMeta = computed(() => {
  const scholarship = props.context?.scholarship
  if (!scholarship) return ''
  const parts = [scholarship.importance ? __(scholarship.importance) : '']
  if (scholarship.confidence !== null && scholarship.confidence !== undefined && scholarship.confidence !== '') {
    parts.push(`${scholarship.confidence}% ${__('confidence')}`)
  }
  return parts.filter(Boolean).join(' · ')
})

function eventStatusLabel(status) {
  const labels = {
    invited: 'Invited',
    registered: 'Registered',
    'checked-in': 'Checked-in',
  }
  const key = String(status || '').trim().toLowerCase().replaceAll('_', '-')
  return __(labels[key] || key)
}
</script>
