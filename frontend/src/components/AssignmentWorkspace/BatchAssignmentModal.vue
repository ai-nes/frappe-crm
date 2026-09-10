<template>
  <Dialog v-model="show" :options="{ title: __('Thiết lập batch Trường → Staff/Team'), size: '4xl' }" @close="reset">
    <template #body-content>
      <div class="space-y-5" data-testid="assignment-batch-modal">
        <div class="rounded-md border border-blue-100 bg-blue-50/70 p-3 text-sm text-blue-900">
          <p class="font-medium">{{ __('Đang chọn {0} trường THPT', [rows.length]) }}</p>
          <p class="mt-1 text-xs">{{ __('Tất cả dòng sẽ được kiểm tra riêng trước khi lưu. Nếu một dòng lỗi, toàn bộ batch sẽ không ghi.') }}</p>
        </div>

        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl
            v-model="teamId"
            type="select"
            :label="__('Team đích')"
            :options="teamOptions"
            :disabled="submitting || previewing"
            required
          />
          <FormControl
            v-model="staffId"
            type="select"
            :label="__('Nhân sự nhận Lead')"
            :options="staffOptions"
            :disabled="!teamId || submitting || previewing"
            required
          />
          <FormControl
            v-model="effectiveFrom"
            type="date"
            :label="__('Ngày phân công')"
            :disabled="submitting || previewing"
            required
          />
          <div class="rounded-md border border-outline-gray-1 bg-surface-gray-2/40 p-3 text-sm">
            <p class="text-xs text-ink-gray-5">{{ __('Revision được khóa theo từng trường') }}</p>
            <p class="mt-1 font-medium text-ink-gray-8">{{ rows.length }} {{ __('revision cần xác nhận') }}</p>
          </div>
        </div>

        <FormControl
          v-model="reason"
          type="textarea"
          :label="__('Lý do thay đổi')"
          :description="__('Bắt buộc. Lý do được lưu vào audit comment của từng mapping.')"
          :disabled="submitting || previewing"
          required
        />

        <section v-if="impact" class="rounded-md border border-amber-200 bg-amber-50/70 p-3 text-sm text-amber-950" aria-live="polite">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <p class="font-medium">{{ __('Preview batch trước khi lưu') }}</p>
            <span :class="impact.all_valid ? 'text-green-700' : 'text-red-700'">
              {{ impact.all_valid ? __('Tất cả dòng hợp lệ') : __('Có dòng cần sửa') }}
            </span>
          </div>
          <div class="mt-2 grid gap-2 sm:grid-cols-3">
            <div>
              <p class="text-xs text-amber-800">{{ __('Trường bị ảnh hưởng') }}</p>
              <p class="font-semibold">{{ impact.affected_high_schools || 0 }}</p>
            </div>
            <div>
              <p class="text-xs text-amber-800">{{ __('Lead hoạt động') }}</p>
              <p class="font-semibold">{{ impact.affected_students || 0 }}</p>
            </div>
            <div>
              <p class="text-xs text-amber-800">{{ __('Mapping sẽ thay thế') }}</p>
              <p class="font-semibold">{{ replacementCount }}</p>
            </div>
          </div>
          <ul class="mt-3 max-h-48 space-y-1 overflow-y-auto border-t border-amber-200 pt-2 text-xs">
            <li v-for="item in impact.rows || []" :key="item.high_school_id" :class="item.valid ? 'text-green-800' : 'text-red-800'">
              <span class="font-medium">{{ item.label }}</span>
              <span v-if="item.valid"> · {{ __('Hợp lệ') }} · revision {{ item.current_revision }}</span>
              <span v-else> · {{ item.error }}</span>
            </li>
          </ul>
          <label class="mt-3 flex items-start gap-2 text-xs font-medium">
            <input v-model="confirmed" type="checkbox" class="mt-0.5 rounded border-outline-gray-3" :disabled="!impact.all_valid" />
            <span>{{ __('Tôi đã xem preview và xác nhận ghi toàn bộ batch.') }}</span>
          </label>
        </section>

        <p v-if="!teamOptions.length" class="rounded-md bg-orange-50 p-3 text-sm text-orange-900" role="alert">
          {{ __('Chưa có Team active đủ điều kiện. Hãy hoàn tất Team Membership trước.') }}
        </p>
        <p v-if="teamId && !staffOptions.length" class="rounded-md bg-orange-50 p-3 text-sm text-orange-900" role="alert">
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
          :label="__('Xem preview batch')"
          :loading="previewing"
          :disabled="!canPreview || submitting"
          data-testid="preview-assignment-batch"
          @click="loadImpact"
        />
        <Button
          variant="solid"
          :label="__('Lưu batch')"
          :loading="submitting"
          :disabled="!canSubmit"
          data-testid="save-assignment-batch"
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
  rows: { type: Array, default: () => [] },
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

const teamOptions = computed(() =>
  (props.options?.teams || []).map((item) => ({ label: item.label || item.value, value: item.value })),
)
const staffOptions = computed(() =>
  (props.options?.staff || [])
    .filter((item) => !teamId.value || item.team_ids?.includes(teamId.value))
    .map((item) => ({ label: item.label || item.value, value: item.value })),
)
const replacementCount = computed(() => (impact.value?.rows || []).filter((item) => item.requires_replacement).length)
const canPreview = computed(() => Boolean(props.rows.length && teamId.value && staffId.value && effectiveFrom.value))
const canSubmit = computed(() => Boolean(canPreview.value && impact.value?.all_valid && confirmed.value && reason.value.trim().length >= 5 && !submitting.value))

watch(show, (open) => {
  if (open) resetForm()
})
watch(teamId, () => {
  if (!staffOptions.value.some((item) => item.value === staffId.value)) staffId.value = ''
  invalidatePreview()
})
watch([staffId, effectiveFrom], invalidatePreview)

function resetForm() {
  const first = props.rows[0]
  teamId.value = first?.team_id || first?.team_ids?.[0] || ''
  staffId.value = first?.staff_id || first?.staff_ids?.[0] || ''
  effectiveFrom.value = new Date().toISOString().slice(0, 10)
  reason.value = ''
  confirmed.value = false
  impact.value = null
  error.value = ''
}

function reset() {
  error.value = ''
  impact.value = null
}

function invalidatePreview() {
  impact.value = null
  confirmed.value = false
}

function schoolIds() {
  return props.rows.map((row) => row.high_school_id).filter(Boolean)
}

async function loadImpact() {
  if (!canPreview.value || previewing.value) return
  previewing.value = true
  error.value = ''
  try {
    impact.value = await call('crm.api.assignment_workspace.get_assignment_batch_impact', {
      high_school_ids: JSON.stringify(schoolIds()),
      team_id: teamId.value,
      staff_id: staffId.value,
    })
  } catch (requestError) {
    error.value = safeCommandError(requestError, __('Không thể tính preview batch.'))
  } finally {
    previewing.value = false
  }
}

async function submit() {
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const expectedRevisions = Object.fromEntries(
      (impact.value?.rows || []).map((item) => [item.high_school_id, item.current_revision]),
    )
    const response = await call('crm.api.assignment_workspace.apply_assignment_batch_command', {
      high_school_ids: JSON.stringify(schoolIds()),
      team_id: teamId.value,
      staff_id: staffId.value,
      effective_from: effectiveFrom.value,
      expected_revisions: JSON.stringify(expectedRevisions),
      reason: reason.value.trim(),
      idempotency_key: createCommandId(),
      correlation_id: createCommandId(),
      replace_existing: true,
    })
    toast.success(__('Đã lưu batch mapping cho {0} trường.', [schoolIds().length]))
    emit('applied', response)
    show.value = false
  } catch (requestError) {
    error.value = safeCommandError(requestError, __('Không thể lưu batch mapping.'))
    if (String(error.value).includes('STALE_ASSIGNMENT_REVISION')) emit('applied', { conflict: true })
  } finally {
    submitting.value = false
  }
}
</script>
