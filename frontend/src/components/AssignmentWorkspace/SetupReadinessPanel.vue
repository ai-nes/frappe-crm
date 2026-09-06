<template>
  <section
    class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 shadow-sm"
  >
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div class="flex items-center gap-2">
          <FeatherIcon
            name="shield"
            class="size-5 text-blue-600"
            aria-hidden="true"
          />
          <h2 class="font-semibold text-ink-gray-9">
            {{ __('Kiểm tra điều kiện nhận Lead') }}
          </h2>
        </div>
      </div>
      <Button
        variant="subtle"
        size="sm"
        :label="__('Làm mới')"
        iconLeft="refresh-cw"
        :loading="loading"
        @click="$emit('refresh')"
      />
    </div>

    <div
      v-if="summary"
      class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-y border-outline-gray-1 py-2 text-sm text-ink-gray-6"
      :aria-label="__('Tóm tắt trạng thái tài khoản')"
    >
      <span>
        <strong class="tabular-nums font-semibold text-ink-gray-9">{{
          summary.accounts || 0
        }}</strong>
        {{ __('người nhận Lead') }}
      </span>
      <span>
        <strong class="tabular-nums font-semibold text-green-700">{{
          summary.ready_accounts || 0
        }}</strong>
        {{ __('đã đủ điều kiện') }}
      </span>
      <span>
        <strong class="tabular-nums font-semibold text-orange-700">{{
          summary.needs_review_accounts || 0
        }}</strong>
        {{ __('cần setup') }}
      </span>
    </div>

    <div class="mt-3">
      <p class="text-xs text-ink-gray-5">
        {{ __('Chỉ hiển thị người có thể tham gia nhận Lead.') }}
      </p>
    </div>

    <div
      v-if="visibleRows.length"
      class="mt-3 max-h-[650px] overflow-auto rounded-md border border-outline-gray-1"
    >
      <table class="w-full min-w-[1200px] table-fixed text-sm">
        <colgroup>
          <col class="w-[230px]" />
          <col class="w-[150px]" />
          <col class="w-[270px]" />
          <col class="w-[290px]" />
          <col class="w-[260px]" />
        </colgroup>
        <thead
          class="sticky top-0 z-10 bg-surface-gray-2 text-left text-xs text-ink-gray-6"
        >
          <tr>
            <th class="px-3 py-2">{{ __('Nhân sự') }}</th>
            <th class="px-3 py-2">{{ __('Vai trò') }}</th>
            <th class="px-3 py-2">{{ __('Nhóm & cơ sở') }}</th>
            <th class="px-3 py-2">{{ __('Cần bổ sung') }}</th>
            <th class="px-3 py-2 text-right">{{ __('Thao tác') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in visibleRows"
            :key="row.id"
            class="border-t border-outline-gray-1 align-top"
          >
            <td class="px-3 py-3">
              <p class="font-medium text-ink-gray-9">{{ row.full_name }}</p>
              <p class="mt-0.5 text-xs text-ink-gray-5">
                {{ row.email || row.user }}
              </p>
            </td>
            <td class="px-3 py-3">
              <p class="font-medium text-ink-gray-9">{{ primaryRole(row) }}</p>
            </td>
            <td class="px-3 py-3">
              <template v-if="row.crm_staff.name">
                <p
                  class="truncate text-sm text-ink-gray-7"
                  :title="row.crm_staff.teams.join(', ')"
                >
                  {{
                    row.crm_staff.teams.length
                      ? row.crm_staff.teams.join(', ')
                      : __('Chưa gán nhóm')
                  }}
                </p>
                <p
                  class="mt-0.5 truncate text-xs"
                  :class="
                    row.crm_staff.campus ? 'text-ink-gray-5' : 'text-orange-700'
                  "
                >
                  {{ row.crm_staff.campus || __('Chưa gán cơ sở') }}
                </p>
              </template>
              <span v-else class="text-orange-700">{{
                __('Chưa có hồ sơ nhân sự')
              }}</span>
            </td>
            <td class="min-w-0 px-3 py-3">
              <IdentityProfileStatus :row="row" />
              <p
                v-if="row.issues.length"
                class="mt-1 max-w-full break-words whitespace-normal text-xs leading-4 text-orange-800"
                :title="issueLabels(row)"
              >
                {{ issueSummary(row) }}
              </p>
              <p v-else class="mt-1 max-w-full whitespace-normal text-xs leading-4 text-ink-gray-5">
                {{ __('Tài khoản đã đủ thông tin') }}
              </p>
            </td>
            <td class="w-[260px] min-w-[260px] whitespace-nowrap px-3 py-3 text-right">
              <div
                class="flex flex-nowrap items-center justify-end gap-2"
                :data-testid="`assignment-actions-${row.user}`"
              >
                <Button
                  v-if="canEditRow(row)"
                  size="sm"
                  variant="solid"
                  :label="__('Hoàn tất setup')"
                  iconLeft="settings"
                  :loading="savingUser === row.user"
                  @click="openStaffContext(row)"
                />
                <Dropdown
                  :options="actionOptions(row)"
                  :button="{
                    label: __('Khác'),
                    iconLeft: 'more-horizontal',
                    variant: 'subtle',
                    loading: savingUser === row.user,
                  }"
                  placement="right"
                />
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p
      v-else
      class="mt-4 rounded-md bg-surface-gray-2 p-4 text-sm text-ink-gray-5"
    >
      {{ __('Không có tài khoản cần hiển thị.') }}
    </p>
    <p v-if="visibleRows.length > maxRows" class="mt-3 text-xs text-ink-gray-5">
      {{ __('Đang hiển thị {0} tài khoản đầu tiên.', [maxRows]) }}
    </p>
    <StaffContextModal
      v-model="staffContextOpen"
      :row="staffContextRow"
      @saved="handleStaffContextSaved"
    />
  </section>
</template>

<script setup>
import { Button, Dropdown, FeatherIcon, call, toast } from 'frappe-ui'
import { computed, ref } from 'vue'
import IdentityProfileStatus from './IdentityProfileStatus.vue'
import StaffContextModal from './StaffContextModal.vue'
import { canonicalRoleOptions } from '@/utils/rolePolicy'

const props = defineProps({
  data: { type: Object, default: null },
  loading: Boolean,
})

const emit = defineEmits(['refresh'])
const maxRows = 30
const savingUser = ref('')
const rows = computed(() => props.data?.rows || [])
const actionRows = computed(() =>
  rows.value.filter((row) => row.status !== 'healthy'),
)
const visibleRows = computed(() => actionRows.value.slice(0, maxRows))
const summary = computed(() => props.data?.summary || {})
const canEditIdentity = computed(() =>
  Boolean(props.data?.capabilities?.can_edit_identity),
)
const staffContextOpen = ref(false)
const staffContextRow = ref(null)

function primaryRole(row) {
  if (row.role_state === 'platform_superuser') return __('Admin')
  if (row.role_state === 'unmapped') return __('Chưa gán vai trò')
  if (row.role_state === 'mixed_or_unmapped') return __('Vai trò cần rà soát')
  return row.crm_profile_label || row.role_state || '—'
}

function issueLabels(row) {
  return row.issues.map((issue) => friendlyIssueLabel(issue)).join(' · ')
}

function issueSummary(row) {
  const labels = row.issues.map((issue) => friendlyIssueLabel(issue))
  const visible = labels.slice(0, 2).join(' · ')
  const remaining = labels.length - 2
  return remaining > 0 ? `${visible} · +${remaining}` : visible
}

function friendlyIssueLabel(issue) {
  const labels = {
    role_not_supported: __('Cần rà soát vai trò'),
    permission_profile_missing: __('Thiếu quyền sử dụng'),
    user_disabled: __('Tài khoản đang tắt'),
    crm_staff_missing: __('Chưa có hồ sơ nhân sự'),
    crm_staff_inactive: __('Hồ sơ nhân sự đang tắt'),
    team_membership_missing: __('Chưa gán nhóm'),
    campus_missing: __('Chưa gán cơ sở'),
  }
  return labels[issue.code] || issue.label
}

function canEditRow(row) {
  return (
    canEditIdentity.value &&
    row.user !== 'Administrator' &&
    row.role_state !== 'system_manager'
  )
}

function actionOptions(row) {
  const options = []
  if (canEditRow(row)) {
    options.push({
      label: __('Đổi vai trò'),
      icon: 'shield',
      submenu: roleOptions(row),
    })
  }
  options.push(
    {
      label: __('Mở tài khoản'),
      icon: 'user',
      onClick: () => openExternal(`/app/user/${encodeURIComponent(row.user)}`),
    },
    {
      label: row.crm_staff.name
        ? __('Mở hồ sơ nhân sự')
        : __('Mở danh sách nhân sự'),
      icon: 'users',
      onClick: () => openExternal(crmStaffHref(row)),
    },
  )
  return options
}

function openExternal(url) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

function roleOptions(row) {
  return canonicalRoleOptions.map((role) => ({
    label: __(role.value === 'System Manager' ? 'Admin' : role.label),
    onClick: () => updateRole(row, role.value),
  }))
}

async function updateRole(row, newRole) {
  if (!row || savingUser.value || row.role_state === newRole) return
  savingUser.value = row.user
  try {
    await call('crm.api.user.update_user_role', {
      user: row.user,
      new_role: newRole,
    })
    toast.success(__('Đã cập nhật vai trò cho {0}.', [row.full_name]))
    emit('refresh')
  } catch (error) {
    toast.error(error?.messages?.[0] || __('Không thể cập nhật vai trò.'))
  } finally {
    savingUser.value = ''
  }
}

function crmStaffHref(row) {
  return row?.crm_staff?.name
    ? `/app/crm-staff/${encodeURIComponent(row.crm_staff.name)}`
    : '/crm-staff'
}

function openStaffContext(row) {
  staffContextRow.value = row
  staffContextOpen.value = true
}

function handleStaffContextSaved() {
  staffContextOpen.value = false
  emit('refresh')
}
</script>
