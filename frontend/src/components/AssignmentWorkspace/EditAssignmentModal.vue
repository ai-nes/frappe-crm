<template>
  <Dialog
    v-model="show"
    :options="{ title: dialogTitle, size: '4xl' }"
    @close="reset"
  >
    <template #body-content>
      <div v-if="row" class="space-y-5" data-testid="assignment-edit-modal">
        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl
            v-model="teamId"
            type="select"
            :label="__('Nhóm phụ trách')"
            :options="teamOptions"
            :disabled="!teamOptions.length || submitting"
            required
          />
          <FormControl
            v-if="row.level === 'high_school'"
            v-model="staffId"
            type="select"
            :label="__('Người nhận Lead')"
            :options="staffOptions"
            :disabled="!staffOptions.length || submitting"
            required
          />
          <FormControl
            v-model="effectiveFrom"
            type="date"
            :label="
              row.level === 'zone' ? __('Có hiệu lực từ') : __('Ngày phân công')
            "
            :disabled="submitting"
            required
          />
        </div>

        <p
          v-if="!teamOptions.length"
          class="rounded-md bg-orange-50 p-3 text-sm text-orange-900"
          role="alert"
        >
          {{
            __(
              'Chưa có Team active đủ điều kiện. Hãy hoàn tất Team Membership trước.',
            )
          }}
        </p>
        <p
          v-if="row.level === 'high_school' && teamId && !staffOptions.length"
          class="rounded-md bg-orange-50 p-3 text-sm text-orange-900"
          role="alert"
        >
          {{ __('Team này chưa có Staff đang hoạt động để nhận trường.') }}
        </p>
        <p
          v-if="error"
          class="rounded-md bg-red-50 p-3 text-sm text-red-900"
          role="alert"
        >
          {{ error }}
        </p>
      </div>
    </template>
    <template #actions>
      <div class="flex w-full justify-end gap-2">
        <Button
          :label="__('Hủy')"
          :disabled="submitting"
          @click="show = false"
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
const error = ref('')
const submitting = ref(false)

const dialogTitle = computed(() =>
  props.row?.level === 'zone'
    ? __('Thiết lập Khu vực → Nhóm')
    : __('Thiết lập Trường → Người phụ trách'),
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
const hasExistingAssignment = computed(
  () =>
    props.row?.assignment_source === 'school_override' ||
    Boolean(props.row?.has_stale_school_override),
)
const canPreview = computed(() =>
  Boolean(
    props.row &&
    teamId.value &&
    (props.row.level !== 'high_school' || staffId.value),
  ),
)
const canSubmit = computed(() => Boolean(canPreview.value && !submitting.value))

watch(show, (open) => {
  if (open) resetForm()
})
watch(teamId, () => {
  if (
    props.row?.level === 'high_school' &&
    !staffOptions.value.some((item) => item.value === staffId.value)
  )
    staffId.value = ''
})

function resetForm() {
  const defaultTeam = props.row?.team_id || props.row?.team_ids?.[0] || ''
  teamId.value = defaultTeam
  staffId.value = props.row?.staff_id || props.row?.staff_ids?.[0] || ''
  effectiveFrom.value =
    props.row?.effective_from || new Date().toISOString().slice(0, 10)
  error.value = ''
}

function reset() {
  error.value = ''
}

async function submit() {
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const response = await call(
      'crm.api.assignment_workspace.apply_assignment_command',
      {
        action: props.row.level === 'zone' ? 'zone_team' : 'school_assignment',
        target_id:
          props.row.level === 'zone'
            ? props.row.zone_id
            : props.row.high_school_id,
        team_id: teamId.value,
        staff_id: props.row.level === 'high_school' ? staffId.value : undefined,
        effective_from: effectiveFrom.value,
        expected_revision: props.row.revision || '0',
        reason:
          props.row.level === 'zone'
            ? `Gán nhóm cho khu vực ${props.row.label || props.row.zone_id} từ màn hình Phân bổ Lead.`
            : `Cập nhật người nhận Lead cho ${props.row.label || props.row.high_school_id} từ màn hình Phân bổ Lead.`,
        idempotency_key: createCommandId(),
        correlation_id: createCommandId(),
        replace_existing: hasExistingAssignment.value,
      },
    )
    toast.success(__('Đã lưu cấu hình phân bổ.'))
    emit('applied', response)
    show.value = false
  } catch (requestError) {
    error.value = safeCommandError(
      requestError,
      __('Không thể lưu cấu hình phân bổ.'),
    )
    if (String(error.value).includes('STALE_ASSIGNMENT_REVISION'))
      emit('applied', { conflict: true })
  } finally {
    submitting.value = false
  }
}
</script>
