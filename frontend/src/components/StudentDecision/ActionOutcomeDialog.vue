<template>
  <Dialog v-model="show" :options="{ title: __('Ghi nhận kết quả tư vấn') }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-sm text-ink-gray-6">{{ action.actionType }} · {{ action.studentName }}</p>
        <FormControl v-model="status" type="select" :label="__('Trạng thái xử lý')" :options="availableTransitions" required />
        <FormControl v-if="status === 'completed' && outcomeOptions.length" v-model="outcomeCode" type="select" :label="__('Kết quả tư vấn')" :options="outcomeOptions" required />
        <FormControl v-if="status === 'completed'" v-model="evidence" type="textarea" :label="__('Nội dung / Ghi chú tư vấn')" :description="__('Ghi nhận chi tiết kết quả trao đổi với thí sinh hoặc phụ huynh.')" required />
        <FormControl v-if="status === 'completed'" v-model="linkedInteraction" :label="__('Cuộc gọi / Tương tác liên quan (tùy chọn)')" />
        <FormControl v-if="['failed', 'cancelled', 'canceled'].includes(status)" v-model="reason" type="textarea" :label="__('Lý do không thành công')" required />
      </div>
      <ErrorMessage v-if="error" class="mt-4" :message="error" role="alert" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Hủy')" :disabled="loading" @click="show = false" />
        <Button variant="solid" theme="blue" :label="__('Lưu kết quả tư vấn')" :loading="loading" :disabled="!canSubmit" @click="submit" />
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
  formatOutcomeLabel,
  formatActionStatusLabel,
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

const availableTransitions = computed(() => (props.action?.permittedTransitions || [])
  .map((transition) => {
    const val = typeof transition === 'string' ? transition : (transition.status || transition.value || transition.to)
    const rawLabel = typeof transition === 'string' ? transition : (transition.label || transition.status || transition.value || transition.to)
    return {
      value: val,
      label: formatActionStatusLabel(rawLabel) || __(rawLabel),
    }
  })
  .filter((transition) => transition.value))

const outcomeOptions = computed(() => (props.action?.outcomeCodes || []).map((outcome) => {
  const code = typeof outcome === 'string' ? outcome : (outcome.value || outcome.name)
  return {
    value: code,
    label: formatOutcomeLabel(code) || __(code),
  }
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
    error.value = safeStudentDecisionError(err, __('Không thể cập nhật công việc này.'))
    if ([409, 412].includes(err?.httpStatusCode || err?.status)) emit('refresh-required')
  } finally {
    loading.value = false
  }
}
</script>
