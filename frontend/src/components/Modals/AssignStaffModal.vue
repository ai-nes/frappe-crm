<template>
  <Dialog v-if="isContact" v-model="show" :options="{ title: __('Assign Staff') }">
    <template #body-content>
      <div class="space-y-1.5">
        <div class="text-sm text-ink-gray-5">{{ __('Staff') }}</div>
        <Link
          class="form-control"
          doctype="CRM Staff"
          :value="staff"
          :placeholder="__('Select staff')"
          @change="(value) => (staff = value)"
        />
      </div>
    </template>
    <template #actions>
      <div class="flex items-center justify-end gap-2">
        <Button
          variant="subtle"
          :label="__('Cancel')"
          @click="show = false"
        />
        <Button
          variant="solid"
          :label="__('Assign Staff')"
          :loading="loading"
          :disabled="!staff"
          @click="assignStaff"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import Link from '@/components/Controls/Link.vue'
import { call, toast } from 'frappe-ui'
import { computed, ref, watchEffect } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  selectedValues: { type: Set, required: true },
})

const emit = defineEmits(['reload'])

const show = defineModel({ type: Boolean })
const isContact = computed(() => props.doctype === 'CRM Contact')

const staff = ref('')
const loading = ref(false)

async function assignStaff() {
  if (!isContact.value) return
  loading.value = true
  try {
    const result = await call('crm.api.staff_assignment.assign_staff', {
      doctype: props.doctype,
      names: JSON.stringify(Array.from(props.selectedValues)),
      staff: staff.value,
    })
    toast.success(__('Assigned staff for {0} record(s)', [result.updated || 0]))
    show.value = false
    staff.value = ''
    emit('reload')
  } finally {
    loading.value = false
  }
}

watchEffect(() => {
  if (show.value && !isContact.value) show.value = false
})
</script>
