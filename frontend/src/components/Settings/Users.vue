<template>
  <div class="flex h-full flex-col gap-6 p-6 text-ink-gray-8">
    <!-- Header -->
    <div class="flex justify-between px-2 pt-2">
      <div class="flex flex-col gap-1 w-9/12">
        <h2 class="flex gap-2 text-xl font-semibold leading-none h-5">
          {{ __('Users') }}
        </h2>
        <p class="text-p-base text-ink-gray-6">
          {{
            __(
              'Manage CRM users by adding or inviting them, and assign roles to control their access and permissions',
            )
          }}
        </p>
      </div>
      <div class="flex item-center space-x-2 w-3/12 justify-end">
        <Dropdown
          :options="[
            {
              label: __('Add Existing User'),
              onClick: () => (showAddExistingModal = true),
            },
            {
              label: __('Invite New User'),
              onClick: () => (activeSettingsPage = 'Invite User'),
            },
          ]"
          :button="{
            label: __('New'),
            iconLeft: 'plus',
            variant: 'solid',
          }"
          placement="right"
        />
      </div>
    </div>

    <!-- loading state -->
    <div v-if="users.loading" class="flex mt-28 justify-between w-full h-full">
      <Button
        :loading="users.loading"
        variant="ghost"
        class="w-full"
        size="2xl"
      />
    </div>

    <!-- Empty State -->
    <EmptyState
      v-if="!users.loading && users.data?.crmUsers?.length == 1"
      name="Users"
      :description="__('Add one to get started.')"
      icon="user"
    />

    <!-- Users List -->
    <div
      v-if="!users.loading && users.data?.crmUsers?.length > 1"
      class="flex flex-col overflow-hidden"
    >
      <div
        v-if="users.data?.crmUsers?.length > 10"
        class="flex items-center justify-between mb-4 px-2 pt-0.5"
      >
        <TextInput
          ref="searchRef"
          v-model="search"
          :placeholder="__('Search User')"
          class="w-1/3"
          :debounce="300"
        >
          <template #prefix>
            <FeatherIcon name="search" class="h-4 w-4 text-ink-gray-6" />
          </template>
        </TextInput>
        <FormControl
          v-model="currentRole"
          type="select"
          :options="[
            { label: __('All'), value: 'All' },
            { label: __('Admin'), value: 'System Manager' },
            { label: __('Sale'), value: 'Sale' },
            { label: __('Marketing'), value: 'Marketing' },
            { label: __('Promoter'), value: 'Promoter' },
            { label: __('Lead Sale'), value: 'Lead Sale' },
            { label: __('Admissions Director'), value: 'Admissions Director' },
          ]"
        />
      </div>
      <ul class="divide-y divide-outline-gray-modals overflow-y-auto px-2">
        <template v-for="user in usersList" :key="user.name">
          <li class="flex items-center justify-between py-2">
            <div class="flex items-center">
              <Avatar
                :image="user.user_image"
                :label="user.full_name"
                size="xl"
              />
              <div class="flex flex-col ml-3">
                <div class="flex items-center text-p-base text-ink-gray-8">
                  {{ user.full_name }}
                </div>
                <div class="text-p-sm text-ink-gray-5">
                  {{ user.name }}
                </div>
                <div
                  v-if="roleStateLabel(user.crm_role_state)"
                  class="text-p-xs text-ink-amber-6"
                >
                  {{ __(roleStateLabel(user.crm_role_state)) }}
                </div>
              </div>
            </div>
            <div class="flex gap-2 items-center flex-row-reverse">
              <Dropdown
                :options="getMoreOptions(user)"
                :button="{
                  icon: 'more-horizontal',
                  onblur: (e) => {
                    e.stopPropagation()
                    confirmRemove = false
                  },
                }"
                placement="right"
              />
              <Tooltip
                v-if="canManageUsers() && user.role == 'System Manager'"
                :text="__('Cannot change role of user with Admin access')"
              >
                <Button :label="__('Admin')" icon-left="shield" />
              </Tooltip>
              <Dropdown
                v-else-if="canManageUsers()"
                :options="getDropdownOptions(user)"
                :button="{
                  label: roleMap[user.role] || user.role,
                  iconRight: 'chevron-down',
                  iconLeft:
                    user.role === 'System Manager'
                      ? 'shield'
                      : user.role === 'Lead Sale'
                        ? 'briefcase'
                        : 'user-check',
                }"
                placement="right"
              />
            </div>
          </li>
        </template>
        <!-- Load More Button -->
        <div
          v-if="!users.loading && users.hasNextPage"
          class="flex justify-center"
        >
          <Button
            class="mt-3.5 p-2"
            :loading="users.loading"
            :label="__('Load More')"
            icon-left="refresh-cw"
            @click="() => users.next()"
          />
        </div>
      </ul>
    </div>
  </div>
  <AddExistingUserModal
    v-if="showAddExistingModal"
    v-model="showAddExistingModal"
  />
</template>

<script setup>
import AddExistingUserModal from '@/components/Modals/AddExistingUserModal.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import { activeSettingsPage } from '@/composables/settings'
import { usersStore } from '@/stores/users'
import { DropdownOption } from '@/utils'
import {
  Dropdown,
  Avatar,
  TextInput,
  toast,
  call,
  FeatherIcon,
  Tooltip,
} from 'frappe-ui'
import { ref, computed, onMounted } from 'vue'
import { ConfirmDelete } from '../../utils'
import {
  canonicalRoleOptions,
  canManageRoles,
  roleStateLabel,
} from '@/utils/rolePolicy'

const { users, getCurrentUser } = usersStore()

const showAddExistingModal = ref(false)
const searchRef = ref(null)
const search = ref('')
const currentRole = ref('All')

const roleMap = {
  'System Manager': __('Admin'),
  Sale: __('Sale'),
  Sales: __('Sales (legacy)'),
  'CTV-Sale': __('Sales (legacy)'),
  Marketing: __('Marketing'),
  'Lead Sale': __('Lead Sale'),
  'Admissions Director': __('Admissions Director'),
}

const canManageUsers = () => canManageRoles(getCurrentUser())

const usersList = computed(() => {
  let filteredUsers =
    users.data?.crmUsers?.filter((user) => user.name !== 'Administrator') || []

  return filteredUsers
    .filter(
      (user) =>
        user.name?.includes(search.value) ||
        user.full_name?.includes(search.value),
    )
    .filter((user) => {
      if (currentRole.value === 'All') return true
      return user.role === currentRole.value
    })
})

const confirmRemove = ref(false)

function getMoreOptions(user) {
  return [
    ...ConfirmDelete({
      onConfirmDelete: () => removeUser(user),
      isConfirmingDelete: confirmRemove,
      label: __('Remove'),
    }),
  ]
}

function getDropdownOptions(user) {
  return canonicalRoleOptions.map((role) => ({
    label: __(role.value === 'System Manager' ? 'Admin' : role.label),
    component: () =>
      DropdownOption({
        option: __(role.value === 'System Manager' ? 'Admin' : role.label),
        icon:
          role.value === 'System Manager'
            ? 'shield'
            : role.value === 'Marketing'
              ? 'user-check'
              : 'briefcase',
        selected: user.role === role.value,
      }),
    onClick: () => updateRole(user, role.value),
  }))
}

function updateRole(user, newRole) {
  if (user.role === newRole) return

  call('crm.api.user.update_user_role', {
    user: user.name,
    new_role: newRole,
  })
    .then(() => {
      toast.success(
        __('{0} has been granted {1} access', [
          user.full_name,
          roleMap[newRole] || newRole,
        ]),
      )
      users.reload()
    })
    .catch((e) => {
      toast.error(e?.messages?.[0] || __('Something went wrong'))
    })
}

function removeUser(user) {
  call('crm.api.user.remove_crm_roles_from_user', {
    user: user.name,
  })
    .then(() => {
      toast.success(__('User {0} has been removed', [user.full_name]))
      users.reload()
    })
    .catch((e) => {
      toast.error(e?.messages?.[0] || __('Something went wrong'))
    })
}

onMounted(() => {
  if (searchRef.value) {
    searchRef.value.el.focus()
  }
})
</script>
