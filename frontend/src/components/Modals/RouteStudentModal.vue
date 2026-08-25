<template>
  <Dialog v-model="show" :options="{ title: __('Retry student routing') }" @close="resetError">
    <template #body-content>
      <p class="text-sm text-ink-gray-6">
        {{ __('Retry this deferred routing request. The server rechecks the current Student ownership, pool policy and eligible members.') }}
      </p>
      <p v-if="routing.last_error_code" class="mt-3 text-sm text-ink-gray-7">
        {{ __('Current reason: {0}', [routing.last_error_code]) }}
      </p>
      <ErrorMessage v-if="error" id="student-route-error" class="mt-4" :message="error" role="alert" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="loading" @click="show = false" />
        <Button variant="solid" :label="__('Retry routing')" :loading="loading" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { call, toast } from 'frappe-ui'
import { ref, watch } from 'vue'
import { isStaleStudentSLAError, safeStudentSLAError } from '@/utils/studentSLA'

const props = defineProps({ routing: { type: Object, required: true } })
const emit = defineEmits(['changed', 'refresh-required'])
const show = defineModel({ type: Boolean })
const loading = ref(false)
const error = ref('')

watch(show, (open) => {
  if (open) error.value = ''
})

function resetError() {
  error.value = ''
}

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const response = await call('crm.api.student_routing.retry_student_routing', { request: props.routing.request })
    toast.success(__('Student routing retry submitted.'))
    emit('changed', response)
    show.value = false
  } catch (err) {
    if (isStaleStudentSLAError(err)) {
      error.value = __('This routing request changed while you were editing. Reload it and review the current state before trying again.')
      emit('refresh-required')
    } else {
      error.value = safeStudentSLAError(err, __('Unable to retry student routing.'))
    }
  } finally {
    loading.value = false
  }
}
</script>
