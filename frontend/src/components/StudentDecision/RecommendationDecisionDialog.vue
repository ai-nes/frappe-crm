<template>
  <Dialog v-model="show" :options="{ title }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-sm text-ink-gray-6">
          {{ __('Deciding recommendation for {0}.', [item.studentName]) }}
        </p>
        <template v-if="status === 'accepted'">
          <FormControl v-model="dueAt" type="datetime-local" :label="__('Due time')" required />
          <FormControl
            v-if="executorOptions.length"
            v-model="assignee"
            type="select"
            :label="__('Executor')"
            :options="executorOptions"
            :description="__('Only executors permitted by the server are shown.')"
          />
        </template>
        <template v-else-if="status === 'deferred'">
          <FormControl v-model="deferKind" type="select" :label="__('Deferral')" :options="deferOptions" required />
          <FormControl v-if="deferKind === 'revisit'" v-model="revisitAt" type="datetime-local" :label="__('Return to inbox at')" required />
        </template>
        <FormControl
          v-if="status === 'rejected' || (status === 'deferred' && deferKind === 'archive')"
          v-model="reason"
          type="textarea"
          :label="status === 'rejected' ? __('Rejection reason') : __('Archival reason')"
          required
        />
      </div>
      <ErrorMessage v-if="error" class="mt-4" :message="error" role="alert" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="loading" @click="show = false" />
        <Button variant="solid" :label="submitLabel" :loading="loading" :disabled="!canSubmit" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import {
  buildRecommendationDecisionPayload,
  createStudentDecisionCommandId,
  safeStudentDecisionError,
  studentDecisionApi,
  validateRecommendationDecision,
} from '@/utils/studentDecision'

const props = defineProps({
  item: { type: Object, required: true },
  status: { type: String, required: true },
})
const emit = defineEmits(['changed', 'refresh-required'])
const show = defineModel({ type: Boolean })
const dueAt = ref('')
const assignee = ref('')
const deferKind = ref('revisit')
const revisitAt = ref('')
const reason = ref('')
const error = ref('')
const loading = ref(false)
const commandKey = ref(createStudentDecisionCommandId())

const title = computed(() => ({
  accepted: __('Accept recommendation'),
  deferred: __('Defer recommendation'),
  rejected: __('Reject recommendation'),
}[props.status] || __('Decide recommendation')))
const submitLabel = computed(() => ({ accepted: __('Accept'), deferred: __('Defer'), rejected: __('Reject') }[props.status] || __('Save')))
const deferOptions = [
  { label: __('Return to inbox later'), value: 'revisit' },
  { label: __('Archive with reason'), value: 'archive' },
]
const executorOptions = computed(() => props.item.permittedExecutors.map((executor) => typeof executor === 'string'
  ? { label: executor, value: executor }
  : { label: executor.label || executor.name || executor.value, value: executor.name || executor.value }))
const validationError = computed(() => validateRecommendationDecision({
  status: props.status, dueAt: dueAt.value, deferKind: deferKind.value, revisitAt: revisitAt.value, reason: reason.value,
}))
const canSubmit = computed(() => !loading.value && !validationError.value)

watch(show, (open) => {
  if (!open) return
  error.value = ''
  commandKey.value = createStudentDecisionCommandId()
  dueAt.value = ''
  assignee.value = ''
  deferKind.value = 'revisit'
  revisitAt.value = ''
  reason.value = ''
})

async function submit() {
  if (!canSubmit.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await call(studentDecisionApi.decideRecommendation, buildRecommendationDecisionPayload({
      item: props.item,
      status: props.status,
      dueAt: dueAt.value,
      assignee: assignee.value,
      deferKind: deferKind.value,
      revisitAt: revisitAt.value,
      reason: reason.value,
      idempotencyKey: commandKey.value,
      correlationId: commandKey.value,
    }))
    emit('changed', response)
    show.value = false
  } catch (err) {
    error.value = safeStudentDecisionError(err, __('Unable to save this decision.'))
    if ([409, 412].includes(err?.httpStatusCode || err?.status)) emit('refresh-required')
  } finally {
    loading.value = false
  }
}
</script>
