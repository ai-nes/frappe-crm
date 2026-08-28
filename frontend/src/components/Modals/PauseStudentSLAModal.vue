<template>
  <Dialog v-model="show" :options="{ title: dialogTitle }" @close="resetError">
    <template #body-content>
      <p class="mb-4 text-sm text-ink-gray-6">
        {{ isPaused ? __('Resume the SLA clock. The elapsed pause will be recorded.') : __('Pause the SLA clock with an approved waiting reason.') }}
      </p>
      <FormControl
        v-if="!isPaused"
        v-model="reasonCode"
        type="select"
        :label="__('Pause reason')"
        :options="reasonOptions"
        required
        :aria-describedby="error ? 'student-sla-pause-error' : undefined"
      />
      <ErrorMessage v-if="error" id="student-sla-pause-error" class="mt-4" :message="error" role="alert" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="loading" @click="show = false" />
        <Button
          variant="solid"
          :label="isPaused ? __('Resume SLA') : __('Pause SLA')"
          :loading="loading"
          :disabled="!canSubmit"
          @click="submit"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import {
  buildPauseSLAPayload,
  buildResumeSLAPayload,
  isStaleStudentSLAError,
  safeStudentSLAError,
} from '@/utils/studentSLA'

const props = defineProps({ attempt: { type: Object, required: true } })
const emit = defineEmits(['changed', 'refresh-required'])
const show = defineModel({ type: Boolean })
const reasonCode = ref('')
const loading = ref(false)
const error = ref('')
const isPaused = computed(() => props.attempt?.status === 'paused')
const dialogTitle = computed(() => (isPaused.value ? __('Resume Student SLA') : __('Pause Student SLA')))
const reasonOptions = computed(() =>
  (props.attempt?.pause_reasons || []).map((reason) => ({ label: reason, value: reason })),
)
const canSubmit = computed(() => !loading.value && (isPaused.value || Boolean(reasonCode.value)))

watch(show, (open) => {
  if (open) {
    reasonCode.value = ''
    error.value = ''
  }
})

function resetError() {
  error.value = ''
}

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const response = await call(
      isPaused.value ? 'crm.api.student_sla.resume_student_sla' : 'crm.api.student_sla.pause_student_sla',
      isPaused.value
        ? buildResumeSLAPayload({ attempt: props.attempt.attempt, revision: props.attempt.revision })
        : buildPauseSLAPayload({ attempt: props.attempt.attempt, reasonCode: reasonCode.value, revision: props.attempt.revision }),
    )
    toast.success(isPaused.value ? __('Student SLA resumed.') : __('Student SLA paused.'))
    emit('changed', response)
    show.value = false
  } catch (err) {
    if (isStaleStudentSLAError(err)) {
      error.value = __('This SLA changed while you were editing. Reload it and review the current state before trying again.')
      emit('refresh-required')
    } else {
      error.value = safeStudentSLAError(err, __('Unable to update the Student SLA.'))
    }
  } finally {
    loading.value = false
  }
}
</script>
