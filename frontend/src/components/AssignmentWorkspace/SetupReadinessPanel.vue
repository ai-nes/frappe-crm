<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 shadow-sm">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div class="flex items-center gap-2">
          <FeatherIcon name="shield" class="size-5 text-blue-600" aria-hidden="true" />
          <h2 class="font-semibold text-ink-gray-9">{{ __('Tài khoản & phân quyền') }}</h2>
        </div>
      </div>
      <Button
        variant="subtle"
        size="sm"
        :label="__('Làm mới kiểm tra')"
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
        <strong class="tabular-nums font-semibold text-ink-gray-9">{{ summary.accounts || 0 }}</strong>
        {{ __('tài khoản') }}
      </span>
      <span>
        <strong class="tabular-nums font-semibold text-green-700">{{ summary.ready_accounts || 0 }}</strong>
        {{ __('sẵn sàng') }}
      </span>
      <span>
        <strong class="tabular-nums font-semibold text-orange-700">{{ summary.needs_review_accounts || 0 }}</strong>
        {{ __('cần rà soát') }}
      </span>
      <span v-if="summary.permission_profile_missing" class="text-orange-700">
        {{ __('Thiếu Permission Profile') }}:
        <strong class="tabular-nums font-semibold">{{ summary.permission_profile_missing }}</strong>
      </span>
      <span v-if="summary.crm_staff_missing" class="text-orange-700">
        {{ __('Thiếu CRM Staff') }}:
        <strong class="tabular-nums font-semibold">{{ summary.crm_staff_missing }}</strong>
      </span>
      <span v-if="summary.team_membership_missing" class="text-orange-700">
        {{ __('Thiếu Team') }}:
        <strong class="tabular-nums font-semibold">{{ summary.team_membership_missing }}</strong>
      </span>
      <span v-if="summary.campus_missing" class="text-orange-700">
        {{ __('Thiếu Campus') }}:
        <strong class="tabular-nums font-semibold">{{ summary.campus_missing }}</strong>
      </span>
    </div>

    <div v-if="visibleRows.length" class="mt-4 overflow-x-auto rounded-md border border-outline-gray-1">
      <table class="w-full min-w-[980px] table-fixed text-sm">
        <thead class="bg-surface-gray-2 text-left text-xs text-ink-gray-6">
          <tr>
            <th class="w-[21%] px-3 py-2">{{ __('Tài khoản') }}</th>
            <th class="w-[18%] px-3 py-2">{{ __('Role') }}</th>
            <th class="w-[27%] px-3 py-2">{{ __('Thông tin phụ trách') }}</th>
            <th class="w-[19%] px-3 py-2">{{ __('Trạng thái') }}</th>
            <th class="w-[15%] px-3 py-2 text-right">{{ __('Thao tác') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in visibleRows" :key="row.id" class="border-t border-outline-gray-1 align-top">
            <td class="px-3 py-3">
              <p class="font-medium text-ink-gray-9">{{ row.full_name }}</p>
              <p class="mt-0.5 text-xs text-ink-gray-5">{{ row.email || row.user }}</p>
            </td>
            <td class="px-3 py-3">
              <p class="font-medium text-ink-gray-9">{{ primaryRole(row) }}</p>
              <p
                v-if="row.roles.length > 1"
                class="mt-1 truncate text-xs text-ink-gray-5"
                :title="row.roles.join(', ')"
              >
                {{ row.roles.length }} {{ __('quyền') }}
              </p>
              <p
                class="mt-1 text-xs"
                :class="row.permission_profile.exists || row.role_state === 'platform_superuser' ? 'text-green-700' : 'text-orange-700'"
              >
                {{ row.permission_profile.exists || row.role_state === 'platform_superuser' ? __('Profile sẵn sàng') : __('Thiếu Profile') }}
              </p>
            </td>
            <td class="px-3 py-3">
              <template v-if="row.crm_staff.name">
                <p class="font-medium text-ink-gray-9">{{ row.crm_staff.full_name || row.crm_staff.name }}</p>
                <p class="mt-1 truncate text-xs text-ink-gray-6" :title="row.crm_staff.teams.join(', ')">
                  {{ row.crm_staff.teams.length ? row.crm_staff.teams.join(', ') : __('Chưa có Team') }}
                </p>
                <p class="mt-0.5 truncate text-xs" :class="row.crm_staff.campus ? 'text-ink-gray-5' : 'text-orange-700'">
                  {{ row.crm_staff.campus || __('Chưa có Campus') }}
                </p>
              </template>
              <span v-else class="text-orange-700">{{ __('Chưa có CRM Staff') }}</span>
            </td>
            <td class="px-3 py-3 text-right">
              <IdentityProfileStatus :row="row" />
              <p
                v-if="row.issues.length"
                class="mt-1 line-clamp-2 text-left text-xs text-orange-800"
                :title="issueLabels(row)"
              >
                {{ issueSummary(row) }}
              </p>
            </td>
            <td class="px-3 py-3 text-right">
              <div :data-testid="`assignment-actions-${row.user}`">
                <Dropdown
                  :options="actionOptions(row)"
                  :button="{
                    label: __('Thao tác'),
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
    <p v-else class="mt-4 rounded-md bg-surface-gray-2 p-4 text-sm text-ink-gray-5">
      {{ __('Không có tài khoản cần hiển thị.') }}
    </p>
    <p v-if="rows.length > maxRows" class="mt-3 text-xs text-ink-gray-5">
      {{ __('Đang hiển thị {0} tài khoản đầu tiên. Dùng bộ lọc hoặc mở Users để xử lý tiếp.', [maxRows]) }}
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
const visibleRows = computed(() => rows.value.slice(0, maxRows))
const summary = computed(() => props.data?.summary || {})
const canEditIdentity = computed(() => Boolean(props.data?.capabilities?.can_edit_identity))
const staffContextOpen = ref(false)
const staffContextRow = ref(null)

function primaryRole(row) {
  if (row.role_state === 'platform_superuser') return __('Admin')
  return row.crm_profile_label || row.role_state || '—'
}

function issueLabels(row) {
  return row.issues.map((issue) => issue.label).join(' · ')
}

function issueSummary(row) {
  const labels = row.issues.map((issue) => issue.label)
  const visible = labels.slice(0, 2).join(' · ')
  const remaining = labels.length - 2
  return remaining > 0 ? `${visible} · +${remaining}` : visible
}

function canEditRow(row) {
  return canEditIdentity.value && row.user !== 'Administrator' && row.role_state !== 'system_manager'
}

function actionOptions(row) {
  const options = []
  if (canEditRow(row)) {
    options.push({
      label: __('Thiết lập Role'),
      icon: 'shield',
      submenu: roleOptions(row),
    })
  }
  options.push(
    {
      label: __('Mở User'),
      icon: 'user',
      onClick: () => openExternal(`/app/user/${encodeURIComponent(row.user)}`),
    },
    {
      label: row.crm_staff.name ? __('Mở CRM Staff') : __('Mở danh sách Staff'),
      icon: 'users',
      onClick: () => openExternal(crmStaffHref(row)),
    },
  )
  if (canEditRow(row)) {
    options.push({
      label: row.crm_staff.name ? __('Chỉnh thông tin phụ trách') : __('Tạo thông tin phụ trách'),
      icon: row.crm_staff.name ? 'edit-2' : 'plus',
      onClick: () => openStaffContext(row),
    })
  }
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
    toast.success(__('Đã cập nhật Role cho {0}. CRM Permission Profile sẽ được resolve lại theo Role.', [row.full_name]))
    emit('refresh')
  } catch (error) {
    toast.error(error?.messages?.[0] || __('Không thể cập nhật Role.'))
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
