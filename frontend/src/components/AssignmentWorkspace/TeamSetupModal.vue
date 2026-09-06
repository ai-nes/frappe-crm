<template>
  <Dialog
    v-model="show"
    :options="{
      title: team?.id ? __('Sửa nhóm') : __('Tạo nhóm'),
      size: '4xl',
    }"
    @close="reset"
  >
    <template #body-content>
      <div class="space-y-4" data-testid="team-setup-modal">
        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl
            v-model="teamName"
            :label="__('Tên Team')"
            :disabled="submitting"
            required
          />
          <FormControl
            v-model="teamType"
            type="select"
            :label="__('Loại nhóm')"
            :options="teamTypeOptions"
            :disabled="submitting"
            required
          />
          <FormControl
            v-model="campus"
            type="select"
            :label="__('Cơ sở')"
            :options="campusOptions"
            :disabled="submitting"
            required
          />
          <FormControl
            v-model="territory"
            type="select"
            :label="__('Phạm vi báo cáo')"
            :options="territoryOptions"
            :disabled="submitting"
          />
        </div>
        <label class="flex items-center gap-2 text-sm text-ink-gray-8">
          <input v-model="isActive" type="checkbox" :disabled="submitting" />
          {{ __('Team đang hoạt động') }}
        </label>
        <section
          v-if="team?.id"
          class="rounded-lg border border-outline-gray-2 bg-surface-gray-1"
          data-testid="team-members-editor"
        >
          <div
            class="flex items-center justify-between gap-3 border-b border-outline-gray-2 px-4 py-3"
          >
            <div>
              <h3 class="font-semibold text-ink-gray-9">
                {{ __('Thành viên nhóm') }}
              </h3>
              <p class="mt-1 text-xs text-ink-gray-6">
                {{ __('Xem và chuyển thành viên sang nhóm khác cùng cơ sở.') }}
              </p>
            </div>
            <span class="text-sm text-ink-gray-5">{{ memberRows.length }}</span>
          </div>
          <div v-if="memberRows.length" class="divide-y divide-outline-gray-2">
            <div
              v-for="member in memberRows"
              :key="member.id"
              class="grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_280px] sm:items-end"
            >
              <div class="min-w-0">
                <p class="truncate font-medium text-ink-gray-9">
                  {{ member.full_name }}
                </p>
                <p class="mt-1 truncate text-xs text-ink-gray-6">
                  {{ member.user }} ·
                  {{ member.membership?.function || __('Chưa có chức năng') }}
                </p>
              </div>
              <FormControl
                v-model="memberMoves[member.id]"
                type="select"
                :label="__('Chuyển sang nhóm')"
                :options="moveTeamOptions(member)"
                :disabled="submitting"
              />
            </div>
          </div>
          <p v-else class="px-4 py-5 text-sm text-ink-gray-6">
            {{ __('Team chưa có thành viên đang hiệu lực.') }}
          </p>
        </section>
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
          :label="__('Lưu Team')"
          :loading="submitting"
          :disabled="!canSubmit"
          data-testid="save-team-setup"
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
  team: { type: Object, default: null },
  options: { type: Object, default: () => ({}) },
  staff: { type: Array, default: () => [] },
  teams: { type: Array, default: () => [] },
})
const emit = defineEmits(['saved'])
const show = defineModel({ type: Boolean })

const teamName = ref('')
const teamType = ref('Sales')
const campus = ref('')
const territory = ref('')
const isActive = ref(true)
const error = ref('')
const submitting = ref(false)
const memberMoves = ref({})

const campusOptions = computed(() => props.options?.campuses || [])
const territoryOptions = computed(() => [
  { label: __('Không chọn'), value: '' },
  ...(props.options?.territories || []),
])
const teamTypeOptions = computed(() => props.options?.team_types || [])
const memberRows = computed(() => {
  if (!props.team?.id) return []
  return (props.staff || [])
    .map((staff) => ({
      ...staff,
      membership: (staff.memberships || []).find(
        (item) => item.team === props.team.id,
      ),
    }))
    .filter((staff) => staff.membership)
})
const canSubmit = computed(() =>
  Boolean(
    teamName.value.trim() &&
    teamType.value &&
    campus.value &&
    !submitting.value,
  ),
)
const pendingMoves = computed(() =>
  memberRows.value
    .filter((member) => memberMoves.value[member.id])
    .map((member) => ({
      staff_id: member.id,
      target_team: memberMoves.value[member.id],
      expected_revision: member.revision,
    })),
)

watch(show, (open) => {
  if (open) resetForm()
})

function resetForm() {
  teamName.value = props.team?.team_name || ''
  teamType.value = props.team?.team_type || 'Sales'
  campus.value = props.team?.campus || campusOptions.value[0]?.value || ''
  territory.value = props.team?.territory || ''
  isActive.value = props.team ? Boolean(props.team.is_active) : true
  error.value = ''
  memberMoves.value = {}
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
      'crm.api.assignment_workspace.apply_team_command',
      {
        team_id: props.team?.id || undefined,
        team_name: teamName.value.trim(),
        team_type: teamType.value,
        campus: campus.value,
        territory: territory.value || undefined,
        is_active: isActive.value,
        expected_revision: props.team?.revision || '0',
        reason: props.team?.id
          ? `Cập nhật Team ${teamName.value.trim()} từ màn hình Phân bổ Lead.`
          : `Tạo nhóm ${teamName.value.trim()} từ màn hình Phân bổ Lead.`,
        member_moves: JSON.stringify(pendingMoves.value),
        idempotency_key: createCommandId(),
        correlation_id: createCommandId(),
      },
    )
    toast.success(__('Đã lưu Team.'))
    emit('saved', response)
    show.value = false
  } catch (requestError) {
    error.value = safeCommandError(requestError, __('Không thể lưu Team.'))
  } finally {
    submitting.value = false
  }
}

function moveTeamOptions(member) {
  return [
    { label: __('Giữ nguyên'), value: '' },
    ...(props.teams || [])
      .filter(
        (item) =>
          item.id !== props.team?.id &&
          item.is_active &&
          item.campus === props.team?.campus &&
          item.campus === member.campus,
      )
      .map((item) => ({ label: item.team_name, value: item.id })),
  ]
}
</script>
