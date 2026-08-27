<template>
  <Dialog v-model="show" :options="{ title: __('Update action') }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-sm text-ink-gray-6">{{ action.actionType }} · {{ action.studentName }}</p>
        <FormControl v-model="status" type="select" :label="__('Next status')" :options="availableTransitions" required />
        <FormControl v-if="status === 'completed' && outcomeOptions.length" v-model="outcomeCode" type="select" :label="__('Execution outcome')" :options="outcomeOptions" required />
        <FormControl v-if="status === 'completed'" v-model="evidence" type="textarea" :label="__('Evidence')" :description="__('Record execution evidence. A linked interaction must belong to this Student and already have its engagement outcome.')" required />
        <FormControl v-if="status === 'completed'" v-model="linkedInteraction" :label="__('Linked interaction (optional)')" />
        <FormControl v-if="['failed', 'cancelled', 'canceled'].includes(status)" v-model="reason" type="textarea" :label="__('Reason')" required />
      </div>
      <ErrorMessage v-if="error" class="mt-4" :message="error" role="alert" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="loading" @click="show = false" />
        <Button variant="solid" :label="__('Save action')" :loading="loading" :disabled="!canSubmit" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import {
  buildActionTransitionPayload,
  createStudentDecisionCommandId,
  safeStudentDecisionError,
  studentDecisionApi,
  transitionOptions,
} from '@/utils/studentDecision'

const props = defineProps({ action: { type: Object, required: true } })
const emit = defineEmits(['changed', 'refresh-required'])
const show = defineModel({ type: Boolean })
const status = ref('')
const outcomeCode = ref('')
const evidence = ref('')
const linkedInteraction = ref('')
const reason = ref('')
const error = ref('')
const loading = ref(false)
const commandKey = ref(createStudentDecisionCommandId())
const availableTransitions = computed(() => transitionOptions(props.action))
const outcomeOptions = computed(() => props.action.outcomeCodes.map((outcome) => {
  if (typeof outcome === 'string') return { label: __(outcome), value: outcome }
  return { ...outcome, label: __(outcome.label || outcome.value) }
}))
const canSubmit = computed(() => !loading.value && status.value &&
  (status.value !== 'completed' || (outcomeCode.value && evidence.value.trim())) &&
  (!['failed', 'cancelled', 'canceled'].includes(status.value) || reason.value.trim()))

watch(show, (open) => {
  if (!open) return
  error.value = ''
  status.value = availableTransitions.value[0]?.value || ''
  outcomeCode.value = ''
  evidence.value = ''
  linkedInteraction.value = ''
  reason.value = ''
  commandKey.value = createStudentDecisionCommandId()
})

async function submit() {
  if (!canSubmit.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await call(studentDecisionApi.transitionAction, buildActionTransitionPayload({
      action: props.action, status: status.value, outcomeCode: outcomeCode.value, evidence: evidence.value,
      reason: reason.value, linkedInteraction: linkedInteraction.value, idempotencyKey: commandKey.value, correlationId: commandKey.value,
    }))
    emit('changed', response)
    show.value = false
  } catch (err) {
    error.value = safeStudentDecisionError(err, __('Unable to update this Action.'))
    if ([409, 412].includes(err?.httpStatusCode || err?.status)) emit('refresh-required')
  } finally {
    loading.value = false
  }
}
</script>
