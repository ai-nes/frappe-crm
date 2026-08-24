<template>
  <Dialog
    v-model="show"
    :options="{ title: __('Add Existing User') }"
    @close="show = false"
  >
    <template #body-content>
      <div class="flex gap-1 border rounded mb-4 p-2 text-ink-gray-5">
        <FeatherIcon name="info" class="size-3.5" />
        <p class="text-sm">
          {{
            __(
              'Add existing system users to this CRM. Assign them a role to grant access with their current credentials.',
            )
          }}
        </p>
      </div>

      <label class="block text-xs text-ink-gray-5 mb-1.5">
        {{ __('Users') }}
      </label>

      <div class="p-2 group bg-surface-gray-2 hover:bg-surface-gray-3 rounded">
        <MultiSelectUserInput
          v-if="users?.data?.crmUsers?.length"
          v-model="newUsers"
          class="flex-1"
          inputClass="!bg-surface-gray-2 hover:!bg-surface-gray-3 group-hover:!bg-surface-gray-3"
          :placeholder="__('john@doe.com')"
          :validate="validateEmail"
          :existingEmails="[
            ...users.data.crmUsers.map((user) => user.name),
            'admin@example.com',
          ]"
          :error-message="
            (value) => __('{0} is an invalid email address', [value])
          "
        />
      </div>
      <FormControl
        v-model="role"
        type="select"
        class="mt-4"
        :label="__('Role')"
        :options="roleOptions"
        :description="description"
      />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button
          variant="solid"
          :label="__('Add')"
          :disabled="!newUsers.length"
          :loading="addNewUser.loading"
          @click="addNewUser.submit()"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import MultiSelectUserInput from '@/components/Controls/MultiSelectUserInput.vue'
import { validateEmail } from '@/utils'
import { usersStore } from '@/stores/users'
import { createResource, toast } from 'frappe-ui'
import { ref, computed } from 'vue'

const { users, isAdmin } = usersStore()

const show = defineModel({ type: Boolean })

const newUsers = ref([])
const role = ref('Sale')

const description = computed(() => {
  return {
    'System Manager':
      'Can manage all aspects of the CRM, including user management, customizations and settings.',
    Sale: 'Can work with permitted admissions records and private reports.',
    Marketing: 'Can access permitted campaign and aggregate CRM information.',
    'Lead Sales': 'Can access Frappe-granted admissions operations for sales leads.',
    'Admissions Director': 'Can access Frappe-granted admissions aggregate information.',
  }[role.value]
})

const roleOptions = computed(() => {
  return [
    { value: 'Sale', label: __('Sales') },
    ...(isAdmin() ? [{ value: 'Marketing', label: __('Marketing') }] : []),
    ...(isAdmin() ? [{ value: 'Lead Sales', label: __('Lead Sales') }] : []),
    ...(isAdmin() ? [{ value: 'Admissions Director', label: __('Admissions Director') }] : []),
    ...(isAdmin() ? [{ value: 'System Manager', label: __('Admin') }] : []),
  ]
})

const addNewUser = createResource({
  url: 'crm.api.user.add_existing_users',
  makeParams: () => ({
    users: JSON.stringify(newUsers.value),
    role: role.value,
  }),
  onSuccess: () => {
    toast.success(__('Users Added Successfully'))
    newUsers.value = []
    show.value = false
    users.reload()
  },
  onError: (error) => {
    toast.error(error.messages[0] || __('Failed to Add Users'))
  },
})
</script>
