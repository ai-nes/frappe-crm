<template>
  <Dialog
    v-model="show"
    :options="{ title: __('Tạo hàng chờ'), size: 'lg' }"
    @close="reset"
  >
    <template #body-content>
      <div class="space-y-4" data-testid="student-pool-setup-modal">
        <p
          class="rounded-lg border border-blue-100 bg-blue-50/60 p-3 text-sm text-blue-900"
        >
          {{
            __(
              'Hàng chờ nhận Lead theo Team. Mỗi Team và Cơ sở nên có một hàng chờ đang hoạt động.',
            )
          }}
        </p>
        <FormControl
          v-model="poolName"
          :label="__('Tên hàng chờ')"
          :disabled="submitting"
          required
        />
        <FormControl
          v-model="team"
          type="select"
          :label="__('Nhóm phụ trách')"
          :options="teamOptions"
          :disabled="submitting"
          required
        />
        <div
          class="rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-3 py-2 text-sm text-ink-gray-7"
        >
          <span class="text-ink-gray-5">{{ __('Cơ sở') }}</span>
          <span class="ml-2 font-medium text-ink-gray-9">{{
            campusLabel || __('Chưa xác định')
          }}</span>
        </div>
        <label class="flex items-center gap-2 text-sm text-ink-gray-8">
          <input v-model="isActive" type="checkbox" :disabled="submitting" />
          {{ __('Hàng chờ đang hoạt động') }}
        </label>
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
          :label="__('Tạo hàng chờ')"
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
  teams: { type: Array, default: () => [] },
})
const emit = defineEmits(['saved'])
const show = defineModel({ type: Boolean })

const poolName = ref('')
const team = ref('')
const isActive = ref(true)
const error = ref('')
const submitting = ref(false)

const teamOptions = computed(() =>
  (props.teams || [])
    .filter((item) => item.is_active && item.team_type === 'Sales')
    .map((item) => ({ label: item.team_name, value: item.id })),
)
const selectedTeam = computed(() =>
  (props.teams || []).find((item) => item.id === team.value),
)
const campusLabel = computed(
  () => selectedTeam.value?.campus_name || selectedTeam.value?.campus || '',
)
const canSubmit = computed(() =>
  Boolean(poolName.value.trim() && team.value && !submitting.value),
)

watch(show, (open) => {
  if (open) resetForm()
})

function resetForm() {
  poolName.value = ''
  team.value = teamOptions.value[0]?.value || ''
  isActive.value = true
  error.value = ''
}

function reset() {
  error.value = ''
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    const response = await call(
      'crm.api.assignment_workspace.create_setup_reference',
      {
        action: 'create_pool',
        name: poolName.value.trim(),
        team: team.value,
        is_active: isActive.value,
        reason: `Tạo hàng chờ ${poolName.value.trim()} từ màn hình Thiết lập phân bổ Lead.`,
        idempotency_key: createCommandId(),
        correlation_id: createCommandId(),
      },
    )
    toast.success(__('Đã tạo hàng chờ.'))
    emit('saved', response)
    show.value = false
  } catch (requestError) {
    error.value = safeCommandError(requestError, __('Không thể tạo hàng chờ.'))
  } finally {
    submitting.value = false
  }
}
</script>
