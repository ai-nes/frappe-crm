<template>
  <Dialog v-model="show" :options="{ title: __('Change student lifecycle') }" @close="resetError">
    <template #body-content>
      <p class="mb-4 text-sm text-ink-gray-6">
        {{ __('Current stage: {0}. The server checks your permission, evidence and the latest revision before recording this transition.', [__(lifecycle.current_stage || lifecycle.stage || 'Unavailable')]) }}
      </p>
      <div v-if="targets.length" class="space-y-4">
        <FormControl v-model="target" type="select" :label="__('New stage')" :options="targets" required />
        <FormControl
          v-if="selectedTarget?.requiresEvidence"
          v-model="outcomeCode"
          type="select"
          :label="__('Qualifying outcome')"
          :options="outcomeOptions"
          required
        />
        <template v-if="selectedTarget?.requiresEvidence">
          <FormControl
            v-model="evidenceReferences"
            type="textarea"
            :label="__('Evidence references')"
            :description="__('Enter one or more category:DocType:record-name references, separated by commas or new lines. Each record is checked against this Student and your read permission.')"
            required
          />
        </template>
        <FormControl
          v-model="reason"
          type="textarea"
          :label="__('Reason')"
          :description="selectedTarget?.requiresReason ? __('A reason is required for this transition and will be recorded in the lifecycle history.') : __('Optional context recorded with this transition.')"
          :required="selectedTarget?.requiresReason"
        />
      </div>
      <p v-else class="text-sm text-ink-gray-5" role="status">{{ __('No lifecycle transitions are currently available to you.') }}</p>
      <ErrorMessage v-if="error" id="student-lifecycle-error" class="mt-4" :message="error" role="alert" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="loading" @click="show = false" />
        <Button variant="solid" :label="__('Record transition')" :loading="loading" :disabled="!canSubmit" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import {
  buildLifecycleTransitionPayload,
  createStudentEngagementCommandId,
  isLifecycleCommandAllowed,
  lifecycleTargets,
  safeLifecycleError,
  studentEngagementApi,
} from '@/utils/studentEngagement'

const props = defineProps({
  student: { type: String, required: true },
  lifecycle: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['changed', 'refresh-required'])
const show = defineModel({ type: Boolean })
const target = ref('')
const evidenceReferences = ref('')
const reason = ref('')
const outcomeCode = ref('qualified')
const error = ref('')
const loading = ref(false)
const idempotencyKey = ref(createStudentEngagementCommandId())
const correlationId = ref(createStudentEngagementCommandId())
const targets = computed(() => lifecycleTargets(props.lifecycle))
const outcomeOptions = ['connected', 'qualified', 'follow_up_required', 'completed'].map((value) => ({
  label: __(value),
  value,
}))
const selectedTarget = computed(() => targets.value.find((item) => item.value === target.value))
const canSubmit = computed(() => !loading.value && isLifecycleCommandAllowed({
  target: target.value,
  reason: reason.value,
  evidence: evidenceReferences.value,
  lifecycle: props.lifecycle,
}))

watch(show, (open) => {
  if (!open) return
  target.value = targets.value[0]?.value || ''
  evidenceReferences.value = ''
  reason.value = ''
  outcomeCode.value = props.lifecycle?.latest_outcome?.outcome || 'qualified'
  error.value = ''
})

function resetError() {
  error.value = ''
}

async function submit() {
  if (!canSubmit.value) return
  error.value = ''
  loading.value = true
  try {
    const response = await call(studentEngagementApi.requestLifecycleTransition, buildLifecycleTransitionPayload({
      student: props.student,
      target: target.value,
      outcomeCode: selectedTarget.value?.requiresEvidence ? outcomeCode.value : undefined,
      reason: reason.value,
      evidence: evidenceReferences.value,
      revision: props.lifecycle.revision,
      idempotencyKey: idempotencyKey.value,
      correlationId: correlationId.value,
    }))
    toast.success(__('Student lifecycle updated.'))
    emit('changed', response)
    show.value = false
    idempotencyKey.value = createStudentEngagementCommandId()
    correlationId.value = createStudentEngagementCommandId()
  } catch (err) {
    error.value = safeLifecycleError(err, __('Unable to change the student lifecycle.'))
    if ([409, 412].includes(err?.httpStatusCode || err?.status)) emit('refresh-required')
  } finally {
    loading.value = false
  }
}
</script>
