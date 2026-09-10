<template>
  <Dialog v-model="show" :options="{ title }">
    <template #body-content>
      <div class="space-y-4">
        <p class="text-sm text-ink-gray-6">
          {{ __('Lên lịch tư vấn cho thí sinh {0}.', [item.studentName]) }}
        </p>
        <template v-if="status === 'accepted'">
          <div class="rounded-md border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm">
            <div class="font-medium text-ink-gray-8">{{ __('Đề xuất của AI (không thể chỉnh sửa)') }}</div>
            <dl class="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-ink-gray-7">
              <dt class="text-ink-gray-5">{{ __('Hành động') }}</dt>
              <dd>{{ aiIdentityLabel }}</dd>
              <dt class="text-ink-gray-5">{{ __('Kênh đề xuất') }}</dt>
              <dd>{{ aiProposal.channel || __('—') }}</dd>
              <dt class="text-ink-gray-5">{{ __('Thời điểm đề xuất') }}</dt>
              <dd>{{ aiProposal.timing || __('—') }}</dd>
            </dl>
          </div>
          <FormControl v-model="dueAt" type="datetime-local" :label="__('Thời hạn thực hiện / Lịch hẹn')" required />
          <label class="flex items-center gap-2 text-sm text-ink-gray-7">
            <input v-model="withChanges" type="checkbox" />
            {{ __('Điều chỉnh kênh / thời điểm thực hiện') }}
          </label>
          <template v-if="withChanges">
            <FormControl v-model="draftChannel" :label="__('Kênh thực hiện (NBA Task)')" :placeholder="aiProposal.channel || ''" />
            <FormControl v-model="draftTiming" type="datetime-local" :label="__('Thời điểm thực hiện (NBA Task)')" />
          </template>
          <FormControl
            v-if="executorOptions.length"
            v-model="assignee"
            type="select"
            :label="__('Tư vấn viên phụ trách')"
            :options="executorOptions"
            :description="__('Chỉ hiển thị các tư vấn viên hợp lệ trong nhóm.')"
          />
        </template>
        <template v-else-if="status === 'deferred'">
          <FormControl v-model="deferKind" type="select" :label="__('Hình thức hẹn lại')" :options="deferOptions" required />
          <FormControl v-if="deferKind === 'revisit'" v-model="revisitAt" type="datetime-local" :label="__('Thời điểm nhắc lại')" required />
        </template>
        <FormControl
          v-if="status === 'rejected' || (status === 'deferred' && deferKind === 'archive')"
          v-model="reason"
          type="textarea"
          :label="status === 'rejected' ? __('Lý do bỏ qua') : __('Lý do đóng đề xuất')"
          required
        />
      </div>
      <ErrorMessage v-if="error" class="mt-4" :message="error" role="alert" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Hủy')" :disabled="loading" @click="show = false" />
        <Button variant="solid" theme="blue" :label="submitLabel" :loading="loading" :disabled="!canSubmit" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, call } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import {
  createStudentDecisionCommandId,
  safeStudentDecisionError,
  validateRecommendationDecision,
} from '@/utils/studentDecision'
import {
  buildRecommendationDecisionCommand,
  recommendationActionIdentity,
  resolveRecommendationOperation,
  studentAdmissionsApi,
} from '@/utils/studentAdmissionsActions'

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
const withChanges = ref(false)
const draftChannel = ref('')
const draftTiming = ref('')
const commandKey = ref(createStudentDecisionCommandId())

// Maps the presentation-level status the queue passes to a decision operation.
const OPERATION_BY_STATUS = { accepted: 'ACCEPT', deferred: 'DEFER', rejected: 'REJECT', dismissed: 'DISMISS' }

const aiProposal = computed(() => {
  const payload = props.item.aiPayload && typeof props.item.aiPayload === 'object' ? props.item.aiPayload : {}
  return {
    ...payload,
    channel: payload.channel ?? props.item.channel ?? props.item.action ?? '',
    timing: payload.timing ?? props.item.timing ?? '',
  }
})
const aiIdentityLabel = computed(() => {
  const identity = recommendationActionIdentity(aiProposal.value)
  return identity.actionType || identity.action || identity.actionId || props.item.action || __('Hành động')
})
const recommendationId = computed(() => props.item.id || props.item.recommendation || props.item.name || '')
const expectedRevision = computed(() => props.item.expectedRevision ?? props.item.revision ?? props.item.version ?? '')

const title = computed(() => ({
  accepted: __('Tiếp nhận & Lên lịch tư vấn'),
  deferred: __('Hẹn liên hệ lại'),
  rejected: __('Từ chối đề xuất liên hệ'),
  dismissed: __('Bỏ qua đề xuất liên hệ'),
}[props.status] || __('Xử lý đề xuất liên hệ')))

const submitLabel = computed(() => ({
  accepted: __('Xác nhận lên lịch'),
  deferred: __('Xác nhận hẹn lại'),
  rejected: __('Xác nhận từ chối'),
  dismissed: __('Xác nhận bỏ qua'),
}[props.status] || __('Lưu')))

const deferOptions = computed(() => [
  { label: __('Nhắc lại sau vào danh sách'), value: 'revisit' },
  { label: __('Đóng đề xuất kèm lý do'), value: 'archive' },
])

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
  withChanges.value = false
  draftChannel.value = ''
  draftTiming.value = ''
})

function draftValues() {
  if (props.status !== 'accepted' || !withChanges.value) return {}
  const draft = {}
  if (draftChannel.value.trim()) draft.channel = draftChannel.value.trim()
  if (draftTiming.value) draft.timing = new Date(draftTiming.value).toISOString()
  return draft
}

async function submit() {
  if (!canSubmit.value) return
  loading.value = true
  error.value = ''
  try {
    const draft = draftValues()
    const intent = OPERATION_BY_STATUS[props.status] || 'REJECT'
    const operation = resolveRecommendationOperation(intent, aiProposal.value, draft)
    const command = buildRecommendationDecisionCommand({
      recommendation: recommendationId.value,
      expectedRevision: expectedRevision.value,
      operation,
      aiPayload: aiProposal.value,
      draft,
      idempotencyKey: commandKey.value,
    })
    // Scheduling / reason metadata rides alongside the append-only command; it
    // never rewrites the immutable AI payload.
    if (dueAt.value) command.due_at = new Date(dueAt.value).toISOString()
    if (assignee.value) command.assignee_staff = assignee.value
    if (props.status === 'deferred') {
      command.defer_kind = deferKind.value
      command.revisit_at = deferKind.value === 'revisit' && revisitAt.value ? new Date(revisitAt.value).toISOString() : null
    }
    if (reason.value.trim()) command.decision_reason = reason.value.trim()
    command.correlation_id = commandKey.value

    const response = await call(studentAdmissionsApi.decideRecommendation, command)
    emit('changed', response)
    show.value = false
  } catch (err) {
    if (err instanceof Error && !err.httpStatusCode && !err.status) {
      error.value = err.message
      return
    }
    error.value = safeStudentDecisionError(err, __('Không thể lưu quyết định này.'))
    if ([409, 412].includes(err?.httpStatusCode || err?.status)) {
      error.value = __('Đề xuất đã thay đổi. Vui lòng tải lại và xem lại trạng thái hiện tại.')
      emit('refresh-required')
    }
  } finally {
    loading.value = false
  }
}
</script>
