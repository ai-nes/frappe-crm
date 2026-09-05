<template>
  <Dialog v-model="show" :options="{ title: dialogTitle, size: '4xl' }" @close="reset">
    <template #body-content>
      <div v-if="row" class="space-y-5" data-testid="assignment-edit-modal">
        <div class="rounded-md border border-blue-100 bg-blue-50/70 p-3 text-sm text-blue-900">
          <p class="font-medium">{{ __('Đang chỉnh sửa cấu hình nguồn') }}</p>
          <p class="mt-1">{{ row.label }} · {{ levelLabel(row.level) }}</p>
          <p class="mt-1 text-xs">{{ __('Lưu sẽ dùng controller của CRM Team Zone Assignment/CRM High School Assignment; không sửa trực tiếp cột current_team hay owner.') }}</p>
        </div>

        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl
            v-model="teamId"
            type="select"
            :label="__('Team đích')"
            :options="teamOptions"
            :disabled="!teamOptions.length || submitting"
            required
          />
          <FormControl
            v-if="row.level === 'high_school'"
            v-model="staffId"
            type="select"
            :label="__('Nhân sự nhận Lead')"
            :options="staffOptions"
            :disabled="!staffOptions.length || submitting"
            required
          />
          <FormControl
            v-model="effectiveFrom"
            type="date"
            :label="row.level === 'zone' ? __('Có hiệu lực từ') : __('Ngày phân công')"
            :disabled="submitting"
            required
          />
        </div>

        <FormControl
          v-model="reason"
          type="textarea"
          :label="__('Lý do thay đổi')"
          :description="__('Bắt buộc. Lý do được lưu vào audit comment của mapping.')"
          :disabled="submitting"
          required
        />

        <section v-if="impact" class="rounded-md border border-amber-200 bg-amber-50/70 p-3 text-sm text-amber-950" aria-live="polite">
          <p class="font-medium">{{ __('Preview ảnh hưởng trước khi lưu') }}</p>
          <div class="mt-2 grid gap-2 sm:grid-cols-3">
            <div>
              <p class="text-xs text-amber-800">{{ __('Trường bị ảnh hưởng') }}</p>
              <p class="font-semibold">{{ impact.impact?.affected_high_schools || 0 }}</p>
            </div>
            <div>
              <p class="text-xs text-amber-800">{{ __('Lead hoạt động') }}</p>
              <p class="font-semibold">{{ impact.impact?.affected_students || 0 }}</p>
            </div>
            <div>
              <p class="text-xs text-amber-800">{{ __('Mapping hiện tại') }}</p>
              <p class="font-semibold">{{ currentAssignmentLabel }}</p>
            </div>
          </div>
          <p v-if="row.level === 'zone' && impact.requires_confirmation" class="mt-2 text-xs text-amber-900">
            {{ __('Đổi Team của Zone có thể đánh dấu các mapping trường cũ cần rà soát.') }}
          </p>
          <p v-if="row.level === 'high_school' && hasExistingAssignment" class="mt-2 text-xs text-amber-900">
            {{ __('Mapping cũ sẽ được chuyển sang Retired; lịch sử không bị xóa.') }}
          </p>
          <label class="mt-3 flex items-start gap-2 text-xs font-medium">
            <input v-model="confirmed" type="checkbox" class="mt-0.5 rounded border-outline-gray-3" />
            <span>{{ __('Tôi đã xem preview và xác nhận thay đổi này.') }}</span>
          </label>
        </section>

        <p v-if="!teamOptions.length" class="rounded-md bg-orange-50 p-3 text-sm text-orange-900" role="alert">
          {{ __('Chưa có Team active đủ điều kiện. Hãy hoàn tất Team Membership trước.') }}
        </p>
        <p v-if="row.level === 'high_school' && teamId && !staffOptions.length" class="rounded-md bg-orange-50 p-3 text-sm text-orange-900" role="alert">
          {{ __('Team này chưa có Staff đang hoạt động để nhận trường.') }}
        </p>
        <p v-if="error" class="rounded-md bg-red-50 p-3 text-sm text-red-900" role="alert">{{ error }}</p>
      </div>
    </template>
    <template #actions>
      <div class="flex w-full justify-end gap-2">
        <Button :label="__('Hủy')" :disabled="submitting" @click="show = false" />
        <Button
          variant="subtle"
          :label="__('Xem ảnh hưởng')"
          :loading="previewing"
          :disabled="!canPreview || submitting"
          @click="loadImpact"
        />
        <Button
          variant="solid"
          :label="__('Lưu cấu hình')"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="submit"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, FormControl, call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { createCommandId, safeCommandError } from '@/utils/studentOwnership'

const props = defineProps({
  row: { type: Object, default: null },
  options: { type: Object, default: () => ({ teams: [], staff: [] }) },
})
const emit = defineEmits(['applied'])
const show = defineModel({ type: Boolean })
const teamId = ref('')
const staffId = ref('')
const effectiveFrom = ref('')
const reason = ref('')
const confirmed = ref(false)
const impact = ref(null)
const error = ref('')
const previewing = ref(false)
const submitting = ref(false)

const levelLabels = { zone: 'Zone', high_school: 'Trường THPT' }
const dialogTitle = computed(() =>
  props.row?.level === 'zone' ? __('Thiết lập Zone → Team') : __('Thiết lập Trường → Staff/Team'),
)
const teamOptions = computed(() =>
  (props.options?.teams || []).map((item) => ({
    label: item.label || item.value,
    value: item.value,
  })),
)
const staffOptions = computed(() =>
  (props.options?.staff || [])
    .filter((item) => !teamId.value || item.team_ids?.includes(teamId.value))
    .map((item) => ({ label: item.label || item.value, value: item.value })),
)
const hasExistingAssignment = computed(() =>
  props.row?.assignment_source === 'school_override' || Boolean(props.row?.has_stale_school_override),
)
const currentAssignmentLabel = computed(() => {
  if (props.row?.level === 'zone') return props.row?.team_name || __('Chưa có')
  if (props.row?.staff_names?.length) return props.row.staff_names.join(', ')
  if (props.row?.team_names?.length) return `${__('Theo Team')}: ${props.row.team_names.join(', ')}`
  return __('Chưa có')
})
const canPreview = computed(() => Boolean(props.row && teamId.value && (props.row.level !== 'high_school' || staffId.value)))
const canSubmit = computed(() => Boolean(canPreview.value && impact.value && confirmed.value && reason.value.trim().length >= 5 && !submitting.value))

watch(show, (open) => {
  if (open) resetForm()
})
watch(teamId, () => {
  if (props.row?.level === 'high_school' && !staffOptions.value.some((item) => item.value === staffId.value)) staffId.value = ''
  impact.value = null
  confirmed.value = false
})
watch([staffId, effectiveFrom, reason], () => {
  impact.value = null
  confirmed.value = false
})

function resetForm() {
  const defaultTeam = props.row?.team_id || props.row?.team_ids?.[0] || ''
  teamId.value = defaultTeam
  staffId.value = props.row?.staff_id || props.row?.staff_ids?.[0] || ''
  effectiveFrom.value = props.row?.effective_from || new Date().toISOString().slice(0, 10)
  reason.value = ''
  confirmed.value = false
  impact.value = null
  error.value = ''
}

function reset() {
  error.value = ''
  impact.value = null
}

async function loadImpact() {
  if (!canPreview.value || previewing.value) return
  previewing.value = true
  error.value = ''
  try {
    impact.value = await call('crm.api.assignment_workspace.get_assignment_impact', {
      action: props.row.level === 'zone' ? 'zone_team' : 'school_assignment',
      target_id: props.row.level === 'zone' ? props.row.zone_id : props.row.high_school_id,
      team_id: teamId.value,
      staff_id: props.row.level === 'high_school' ? staffId.value : undefined,
    })
  } catch (requestError) {
    error.value = safeCommandError(requestError, __('Không thể tính preview ảnh hưởng.'))
  } finally {
    previewing.value = false
  }
}

async function submit() {
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const response = await call('crm.api.assignment_workspace.apply_assignment_command', {
      action: props.row.level === 'zone' ? 'zone_team' : 'school_assignment',
      target_id: props.row.level === 'zone' ? props.row.zone_id : props.row.high_school_id,
      team_id: teamId.value,
      staff_id: props.row.level === 'high_school' ? staffId.value : undefined,
      effective_from: effectiveFrom.value,
      expected_revision: props.row.revision || '0',
      reason: reason.value.trim(),
      idempotency_key: createCommandId(),
      correlation_id: createCommandId(),
      replace_existing: hasExistingAssignment.value,
    })
    toast.success(__('Đã lưu cấu hình phân bổ.'))
    emit('applied', response)
    show.value = false
  } catch (requestError) {
    error.value = safeCommandError(requestError, __('Không thể lưu cấu hình phân bổ.'))
    if (String(error.value).includes('STALE_ASSIGNMENT_REVISION')) emit('applied', { conflict: true })
  } finally {
    submitting.value = false
  }
}

function levelLabel(level) {
  return levelLabels[level] || level
}
</script>
