<template>
  <section class="border-b p-1 sm:p-3" aria-label="Marketing attribution">
    <Section :label="__('Marketing attribution')" label-class="px-2 font-semibold" header-class="h-8">
      <template #actions>
        <Button
          v-if="canManage"
          size="sm"
          :label="__('Record evidence')"
          @click="openEntry()"
        />
      </template>
      <div class="space-y-3 px-3 pb-3 text-sm">
        <p v-if="resource.loading" class="text-ink-gray-5" role="status">{{ __('Loading attribution…') }}</p>
        <p v-else-if="resource.error" class="text-red-600" role="alert">{{ errorMessage }}</p>
        <template v-else>
          <div v-if="metrics.length" class="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Attribution funnel metrics">
            <div v-for="metric in metrics" :key="metric.label" class="rounded bg-surface-gray-1 px-2 py-1.5">
              <p class="text-xs text-ink-gray-5">{{ metric.label }}</p>
              <p class="font-semibold text-ink-gray-8">{{ metric.value }}</p>
            </div>
          </div>
          <p v-else class="text-ink-gray-5">{{ __('No attribution metrics are available yet.') }}</p>

          <ol v-if="timeline.length" class="divide-y" aria-label="Attribution evidence timeline">
            <li v-for="item in timeline" :key="item.name" class="flex items-start justify-between gap-3 py-2">
              <div class="min-w-0">
                <p class="truncate font-medium text-ink-gray-8">
                  {{ item.label }}
                  <span v-if="item.student" class="font-normal text-ink-gray-6"> · {{ __('Student {0}', [item.student]) }}</span>
                </p>
                <p class="text-xs text-ink-gray-5">{{ formatDate(item.occurredAt) }}</p>
                <p v-if="item.notes" class="mt-1 text-ink-gray-6">{{ item.notes }}</p>
                <p v-if="item.superseded" class="mt-1 text-xs text-ink-gray-5">{{ __('Superseded evidence') }}</p>
              </div>
              <Button
                v-if="canManage && item.name && !item.superseded"
                size="sm"
                :label="__('Correct')"
                @click="openEntry(item)"
              />
            </li>
          </ol>
          <p v-else class="text-ink-gray-5">{{ __('No attribution evidence has been recorded.') }}</p>
        </template>
      </div>
    </Section>
  </section>

  <Dialog v-model="showEntry" :options="{ title: entry.supersedes ? __('Correct attribution evidence') : __('Record attribution evidence') }" @close="resetEntry">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-sm text-ink-gray-6">{{ entry.supersedes ? __('A correction creates new evidence and retains the previous record.') : __('Record a Student-anchored attribution event. Student information is not opened from this screen.') }}</p>
        <FormControl v-model="entry.student" :label="__('Student reference')" :description="__('Enter the approved Student ID.')" required />
        <FormControl v-model="entry.contact" :label="__('Contact reference (optional)')" :description="__('Only provide it when it belongs to the same Student.')" />
        <FormControl v-if="kind === 'campaign'" v-model="entry.source" type="select" :label="__('Source')" :options="campaignSources" required />
        <FormControl v-else v-model="entry.status" type="select" :label="__('Participation status')" :options="eventStatuses" required />
        <FormControl v-model="entry.occurredAt" type="datetime-local" :label="dateLabel" />
        <FormControl v-model="entry.notes" type="textarea" :label="__('Notes')" />
        <ErrorMessage v-if="entryError" :message="entryError" role="alert" />
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="saving" @click="showEntry = false" />
        <Button variant="solid" :label="entry.supersedes ? __('Record correction') : __('Record evidence')" :loading="saving" :disabled="!canSubmit" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import Section from '@/components/Section.vue'
import { usersStore } from '@/stores/users'
import { canManageAttribution } from '@/utils/rolePolicy'
import {
  attributionApi,
  attributionMetrics,
  attributionReadApi,
  attributionTimeline,
  buildAttributionPayload,
  createAttributionCommandId,
  safeAttributionError,
} from '@/utils/attribution'
import { Button, Dialog, ErrorMessage, FormControl, call, createResource, toast } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  kind: { type: String, required: true, validator: (value) => ['campaign', 'event'].includes(value) },
  record: { type: String, required: true },
})
const { getCurrentUser } = usersStore()
const showEntry = ref(false)
const saving = ref(false)
const entryError = ref('')
const commandId = ref(createAttributionCommandId())
const entry = ref(emptyEntry())
const campaignSources = ['Manual']
const eventStatuses = ['Registered', 'Checked-in', 'No-show', 'Feedback Given']

// Phase 7 integration contract: these are redacted aggregate/timeline DTOs.
// They must never contain a Student name, profile data, or a navigable route.
const resource = createResource({
  url: attributionReadApi(props.kind),
  makeParams: () => props.kind === 'event' ? { crm_event: props.record } : { crm_campaign: props.record },
  auto: true,
  initialData: null,
})
const canManage = computed(() => canManageAttribution(getCurrentUser()))
const metrics = computed(() => attributionMetrics(resource.data || {}))
const timeline = computed(() => attributionTimeline(resource.data || {}))
const errorMessage = computed(() => safeAttributionError(resource.error, __('Unable to load attribution.')))
const dateLabel = computed(() => props.kind === 'event' ? __('Registered at') : __('Touched at'))
const canSubmit = computed(() => !saving.value && entry.value.student.trim())

function emptyEntry() {
  return { student: '', contact: '', source: 'Manual', status: 'Registered', occurredAt: '', notes: '', supersedes: null }
}

function openEntry(item = null) {
  entryError.value = ''
  commandId.value = createAttributionCommandId()
  entry.value = {
    ...emptyEntry(),
    student: item?.student || '',
    source: item?.source || 'Manual',
    status: item?.status || 'Registered',
    supersedes: item?.name || null,
  }
  showEntry.value = true
}

function resetEntry() {
  entryError.value = ''
}

function formatDate(value) {
  if (!value) return __('Time unavailable')
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

async function submit() {
  if (!canSubmit.value || !canManage.value) return
  saving.value = true
  entryError.value = ''
  try {
    await call(
      props.kind === 'event' ? attributionApi.recordEventParticipation : attributionApi.recordCampaignTouchpoint,
      buildAttributionPayload({ kind: props.kind, record: props.record, ...entry.value, idempotencyKey: commandId.value }),
    )
    toast.success(entry.value.supersedes ? __('Attribution correction recorded.') : __('Attribution evidence recorded.'))
    showEntry.value = false
    resource.reload()
  } catch (error) {
    entryError.value = safeAttributionError(error, __('Unable to record attribution evidence.'))
  } finally {
    saving.value = false
  }
}
</script>
