<template>
  <Dialog
    v-model="show"
    :options="{
      title: row?.crm_staff?.name
        ? __('Chỉnh thông tin phụ trách')
        : __('Tạo thông tin phụ trách'),
      size: '4xl',
    }"
    @close="reset"
  >
    <template #body-content>
      <div class="space-y-5" data-testid="staff-context-modal">
        <div
          class="rounded-md border border-blue-100 bg-blue-50/70 p-3 text-sm text-blue-900"
        >
          <p class="font-medium">{{ row?.full_name || row?.user }}</p>
          <p class="mt-1 text-xs">
            {{
              __(
                'Vai trò tài khoản quản lý ở phần Tài khoản. Tại đây bạn gắn cơ sở và nhóm phụ trách.',
              )
            }}
          </p>
        </div>

        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl
            v-model="fullName"
            :label="__('Họ tên nhân sự')"
            :disabled="loading || submitting"
            required
          />
          <FormControl
            v-model="user"
            :label="__('Tài khoản')"
            :type="row?.crm_staff?.name ? 'text' : 'select'"
            :options="userOptions"
            :disabled="Boolean(row?.crm_staff?.name) || loading || submitting"
            required
          />
          <FormControl
            v-model="campus"
            type="select"
            :label="__('Cơ sở')"
            :options="campusOptions"
            :disabled="loading || submitting"
            required
          />
          <FormControl
            v-model="department"
            type="select"
            :label="__('Phòng ban')"
            :options="departmentOptions"
            :disabled="!campus || loading || submitting"
            required
          />
          <FormControl
            v-model="isActive"
            type="select"
            :label="__('Trạng thái Staff')"
            :options="activeOptions"
            :disabled="loading || submitting"
            required
          />
        </div>

        <section class="rounded-md border border-outline-gray-1 p-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 class="text-sm font-semibold text-ink-gray-9">
                {{ __('Team phụ trách') }}
              </h3>
              <p class="mt-1 text-xs text-ink-gray-5">
                {{ __('Chỉ Team đang hiệu lực mới được phân bổ Lead.') }}
              </p>
            </div>
            <Button
              size="sm"
              variant="subtle"
              :label="__('Thêm nhóm')"
              iconLeft="plus"
              :disabled="loading || submitting"
              @click="addMembership"
            />
          </div>
          <div v-if="memberships.length" class="mt-3 space-y-3">
            <div
              v-for="(membership, index) in memberships"
              :key="membership.key"
              class="rounded-md border border-outline-gray-1 bg-surface-gray-2/30 p-3"
            >
              <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <FormControl
                  v-model="membership.team"
                  type="select"
                  :label="__('Nhóm')"
                  :options="teamOptions"
                  :disabled="loading || submitting"
                  required
                />
                <FormControl
                  v-model="membership.function"
                  type="select"
                  :label="__('Chức năng')"
                  :options="functionOptions"
                  :disabled="loading || submitting"
                  required
                />
                <FormControl
                  v-model="membership.term"
                  :label="__('Kỳ tuyển sinh')"
                  :disabled="loading || submitting"
                />
                <FormControl
                  v-model="membership.effective_from"
                  type="date"
                  :label="__('Hiệu lực từ')"
                  :disabled="loading || submitting"
                />
                <FormControl
                  v-model="membership.effective_until"
                  type="date"
                  :label="__('Hiệu lực đến')"
                  :disabled="loading || submitting"
                />
                <label class="flex items-center gap-2 self-end pb-2 text-sm">
                  <input
                    v-model="membership.is_primary"
                    type="checkbox"
                    :disabled="loading || submitting"
                  />
                  {{ __('Nhóm chính') }}
                </label>
              </div>
              <button
                type="button"
                class="mt-2 text-xs font-medium text-red-600 hover:underline"
                :disabled="loading || submitting"
                @click="removeMembership(index)"
              >
                {{ __('Xóa khỏi danh sách nhóm') }}
              </button>
            </div>
          </div>
          <p
            v-else
            class="mt-3 rounded-md bg-orange-50 p-3 text-sm text-orange-900"
          >
            {{
              __(
                'Chưa có Team phụ trách. Nhân sự chưa đủ điều kiện nhận Lead tự động.',
              )
            }}
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
          :disabled="loading || submitting"
          @click="show = false"
        />
        <Button
          variant="solid"
          :label="__('Lưu thông tin phụ trách')"
          :loading="submitting"
          :disabled="!canSubmit"
          data-testid="save-staff-context"
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

const props = defineProps({ row: { type: Object, default: null } })
const emit = defineEmits(['saved'])
const show = defineModel({ type: Boolean })

const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const context = ref(null)
const fullName = ref('')
const user = ref('')
const campus = ref('')
const department = ref('')
const isActive = ref('1')
const memberships = ref([])

const campusOptions = computed(() =>
  (context.value?.options?.campuses || []).map((item) => ({
    label: item.label || item.value,
    value: item.value,
  })),
)
const userOptions = computed(() =>
  (context.value?.options?.users || []).map((item) => ({
    label: `${item.label || item.value} · ${item.email || item.value}`,
    value: item.value,
  })),
)
const departmentOptions = computed(() =>
  (context.value?.options?.departments || [])
    .filter((item) => !campus.value || item.campus === campus.value)
    .map((item) => ({ label: item.label || item.value, value: item.value })),
)
const teamOptions = computed(() =>
  (context.value?.options?.teams || [])
    .filter((item) => !campus.value || item.campus === campus.value)
    .map((item) => ({ label: item.label || item.value, value: item.value })),
)
const functionOptions = computed(() =>
  (context.value?.options?.functions || []).map((value) => ({
    label: value,
    value,
  })),
)
const activeOptions = [
  { label: __('Đang hoạt động'), value: '1' },
  { label: __('Đã tắt'), value: '0' },
]
const canSubmit = computed(() =>
  Boolean(
    fullName.value.trim() &&
    user.value.trim() &&
    campus.value &&
    department.value &&
    !loading.value &&
    !submitting.value,
  ),
)

watch(show, (open) => {
  if (open) loadContext()
})
watch(campus, () => {
  if (
    !departmentOptions.value.some((option) => option.value === department.value)
  )
    department.value = ''
})
watch(user, (value) => {
  if (props.row?.crm_staff?.name || !value || fullName.value) return
  const option = context.value?.options?.users?.find(
    (item) => item.value === value,
  )
  if (option?.label) fullName.value = option.label
})

async function loadContext() {
  loading.value = true
  error.value = ''
  try {
    context.value = await call(
      'crm.api.assignment_workspace.get_staff_context',
      {
        staff_id: props.row?.crm_staff?.name || undefined,
        user: props.row?.user || undefined,
      },
    )
    const staff = context.value?.staff || {}
    fullName.value = staff.full_name || props.row?.full_name || ''
    user.value = context.value?.user || props.row?.user || ''
    campus.value = staff.campus || ''
    department.value = staff.department || ''
    isActive.value = staff.is_active === false ? '0' : '1'
    memberships.value = (context.value?.memberships || []).map((item) => ({
      key: item.name || createCommandId(),
      team: item.team || '',
      function: item.function || 'Sale',
      term: item.term || '',
      effective_from: item.effective_from || '',
      effective_until: item.effective_until || '',
      is_primary: Boolean(item.is_primary),
    }))
  } catch (requestError) {
    error.value = safeCommandError(
      requestError,
      __('Không thể tải thông tin phụ trách.'),
    )
  } finally {
    loading.value = false
  }
}

function addMembership() {
  memberships.value.push({
    key: createCommandId(),
    team: '',
    function: 'Sale',
    term: '',
    effective_from: '',
    effective_until: '',
    is_primary: false,
  })
}

function removeMembership(index) {
  memberships.value.splice(index, 1)
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
      'crm.api.assignment_workspace.apply_staff_context_command',
      {
        staff_id: context.value?.staff?.name || undefined,
        user: user.value.trim(),
        full_name: fullName.value.trim(),
        department: department.value,
        campus: campus.value,
        is_active: isActive.value,
        memberships: JSON.stringify(
          memberships.value.map((item) =>
            Object.fromEntries(
              Object.entries(item).filter(([field]) => field !== 'key'),
            ),
          ),
        ),
        expected_revision: context.value?.revision || '0',
        reason: context.value?.staff?.name
          ? `Cập nhật nhân sự ${fullName.value.trim()} từ màn hình Phân bổ Lead.`
          : `Tạo nhân sự ${fullName.value.trim()} từ màn hình Phân bổ Lead.`,
        idempotency_key: createCommandId(),
        correlation_id: createCommandId(),
      },
    )
    toast.success(__('Đã lưu thông tin phụ trách.'))
    emit('saved', response)
    show.value = false
  } catch (requestError) {
    error.value = safeCommandError(
      requestError,
      __('Không thể lưu thông tin phụ trách.'),
    )
  } finally {
    submitting.value = false
  }
}
</script>
