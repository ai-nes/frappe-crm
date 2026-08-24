<template>
  <Dialog v-model="show" :options="{ title: __('Resolve student intake review') }">
    <template #body-content>
      <p class="mb-4 text-sm text-ink-gray-6">
        {{ __('Choose a review decision. Candidate details are limited to records you may access.') }}
      </p>
      <div class="space-y-4">
        <FormControl v-model="decision" type="select" :label="__('Decision')" :options="decisionOptions" />
        <FormControl
          v-if="decision === 'attach_identity'"
          v-model="selectedIdentity"
          type="select"
          :label="__('Existing identity')"
          :options="candidateOptions"
          :description="__('Select the identity verified for this intake.')"
          required
        />
        <p v-if="decision === 'attach_identity' && !candidateOptions.length" class="text-sm text-ink-red-3" role="alert">
          {{ __('No accessible identity candidate is available. Choose another decision or refresh the review.') }}
        </p>
        <template v-if="decision === 'approve_new_identity'">
          <FormControl v-model="newIdentity.student_name" :label="__('Verified student name')" required />
          <FormControl
            v-model="newIdentity.national_id"
            :label="__('Verified national ID')"
            :description="__('Use a verified 9- or 12-digit identifier. This creates a new identity.')"
            inputmode="numeric"
            required
          />
          <FormControl v-model="newIdentity.phone" :label="__('Phone (optional)')" type="tel" />
          <FormControl v-model="newIdentity.email" :label="__('Email (optional)')" type="email" />
        </template>
        <FormControl
          v-model="evidence"
          type="textarea"
          :label="__('Decision evidence')"
          :description="__('Required for an auditable review decision.')"
          required
        />
      </div>
      <ErrorMessage v-if="error" class="mt-4" :message="error" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="loading" @click="show = false" />
        <Button variant="solid" :label="__('Save decision')" :loading="loading" :disabled="!isValid" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { call, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import {
  createCommandId,
  isValidIntakeReviewDecision,
  reviewCandidateOptions,
  safeCommandError,
} from '@/utils/studentOwnership'

const props = defineProps({ review: { type: Object, required: true } })
const emit = defineEmits(['resolved'])
const show = defineModel({ type: Boolean })
const decision = ref('attach_identity')
const selectedIdentity = ref('')
const evidence = ref('')
const newIdentity = reactive({ student_name: '', national_id: '', phone: '', email: '' })
const loading = ref(false)
const error = ref('')
const idempotencyKey = ref(createCommandId())
const correlationId = ref(createCommandId())
const decisionOptions = [
  { label: __('Attach existing identity'), value: 'attach_identity' },
  { label: __('Approve new verified identity'), value: 'approve_new_identity' },
  { label: __('Reject intake'), value: 'reject' },
]
const candidateOptions = computed(() => reviewCandidateOptions(props.review))
const isValid = computed(() =>
  isValidIntakeReviewDecision({
    decision: decision.value,
    evidence: evidence.value,
    identityId: selectedIdentity.value,
    identityData: newIdentity,
    availableIdentityIds: candidateOptions.value.map((candidate) => candidate.value),
  }),
)

watch(
  candidateOptions,
  (options) => {
    if (!selectedIdentity.value && options.length === 1) selectedIdentity.value = options[0].value
  },
  { immediate: true },
)

async function submit() {
  if (loading.value || !isValid.value) return
  error.value = ''
  loading.value = true
  try {
    const response = await call('crm.api.student_intake.decide_intake_review', {
      review_id: props.review.review_id || props.review.name,
      decision: decision.value,
      identity_id: decision.value === 'attach_identity' ? selectedIdentity.value : null,
      identity_data: decision.value === 'approve_new_identity'
        ? { ...newIdentity, national_id: newIdentity.national_id.replace(/[ .-]/g, '') }
        : null,
      evidence_refs: [evidence.value.trim()],
      reason: evidence.value.trim(),
      expected_review_id: props.review.review_id || props.review.name,
      expected_revision: props.review.revision ?? 0,
      idempotency_key: idempotencyKey.value,
      correlation_id: correlationId.value,
    })
    toast.success(__('Intake review decision saved.'))
    emit('resolved', response)
    show.value = false
    idempotencyKey.value = createCommandId()
    correlationId.value = createCommandId()
  } catch (err) {
    error.value = safeCommandError(err, __('Unable to save the review decision.'))
  } finally {
    loading.value = false
  }
}
</script>
