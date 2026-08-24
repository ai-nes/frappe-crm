<template>
  <Dialog v-model="show" :options="{ title: __('New student intake'), size: 'lg' }">
    <template #body-content>
      <p class="mb-4 text-sm text-ink-gray-6">
        {{ __('A national ID is a strong identifier. Phone and email can be shared and may require review.') }}
      </p>
      <div class="grid gap-4 sm:grid-cols-2">
        <FormControl v-model="form.student_name" :label="__('Student name')" required autofocus />
        <FormControl v-model="form.admission_year" :label="__('Admission year')" required />
        <FormControl v-model="form.branch" :label="__('Campus')" required />
        <FormControl v-model="form.owning_team" :label="__('Initial pool (optional)')" />
        <FormControl v-model="identifiers.id_number" :label="__('National ID (strong identifier)')" />
        <FormControl v-model="form.phone" :label="__('Phone (weak identifier)')" type="tel" />
        <FormControl v-model="form.email" :label="__('Email (weak identifier)')" type="email" class="sm:col-span-2" />
      </div>
      <ErrorMessage v-if="error" class="mt-4" :message="error" />
      <div v-if="result" class="mt-4 rounded border p-3 text-sm" role="status" aria-live="polite">
        {{ resultMessage }}
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="loading" @click="show = false" />
        <Button variant="solid" :label="__('Submit intake')" :loading="loading" :disabled="!isValid" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { call, toast } from 'frappe-ui'
import { computed, reactive, ref } from 'vue'
import { buildIntakePayload, createCommandId, intakeResultKind, safeCommandError } from '@/utils/studentOwnership'

const emit = defineEmits(['completed', 'review-required'])
const show = defineModel({ type: Boolean })
const form = reactive({ student_name: '', admission_year: '', branch: '', owning_team: '', phone: '', email: '' })
const identifiers = reactive({ id_number: '', source_record_id: createCommandId() })
const idempotencyKey = ref(createCommandId())
const loading = ref(false)
const error = ref('')
const result = ref(null)

const isValid = computed(() => Boolean(form.student_name.trim() && form.admission_year && form.branch))
const resultMessage = computed(() => {
  const messages = {
    attached: __('Intake attached to the existing admission case.'),
    created: __('Student intake created.'),
    review_required: __('A review is required before this intake can continue.'),
  }
  return messages[intakeResultKind(result.value)] || __('Intake completed.')
})

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const payload = {
      ...buildIntakePayload(form, identifiers),
      idempotency_key: idempotencyKey.value,
      correlation_id: createCommandId(),
    }
    const response = await call('crm.api.student_intake.submit_intake', payload)
    const kind = intakeResultKind(response)
    if (!kind) throw new Error(__('The intake service returned an invalid result.'))
    result.value = response
    if (kind === 'review_required') emit('review-required', response)
    else emit('completed', response)
    toast.success(resultMessage.value)
    // A receipt is terminal: do not reuse this source operation for the next explicit intake.
    idempotencyKey.value = createCommandId()
  } catch (err) {
    error.value = safeCommandError(err, __('Unable to submit intake.'))
  } finally {
    loading.value = false
  }
}
</script>
