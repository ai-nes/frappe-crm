<template>
  <Dialog v-model="show" :options="{ title: __('Change student ownership') }" @close="resetError">
    <template #body-content>
      <p class="mb-4 text-sm text-ink-gray-6">{{ __('Choose either an individual owner or a campus pool. The server verifies eligibility and scope.') }}</p>
      <div class="space-y-4">
        <FormControl v-model="targetKind" type="select" :label="__('Assign to')" :options="targetKinds" />
        <FormControl v-model="targetId" type="select" :label="targetKind === 'owner' ? __('Eligible owner') : __('Eligible pool')" :options="targetOptions" :disabled="targets.loading" required />
        <FormControl v-model="reason" type="textarea" :label="__('Reason')" :description="__('This reason is recorded in the ownership history.')" required />
      </div>
      <ErrorMessage v-if="error" class="mt-4" :message="error" />
      <p v-if="targets.loading" class="mt-3 text-sm text-ink-gray-5" role="status">{{ __('Loading eligible ownership targets…') }}</p>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="loading" @click="show = false" />
        <Button variant="solid" :label="__('Save ownership')" :loading="loading" :disabled="!canSubmit" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { call, createResource, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { buildOwnershipPayload, createCommandId, isStaleOwnershipError, safeCommandError } from '@/utils/studentOwnership'

const props = defineProps({ student: { type: String, required: true }, ownership: { type: Object, default: () => ({}) } })
const emit = defineEmits(['changed', 'refresh-required'])
const show = defineModel({ type: Boolean })
const targetKind = ref('pool')
const targetId = ref('')
const reason = ref('')
const loading = ref(false)
const error = ref('')
const targetKinds = [
  { label: __('Campus pool'), value: 'pool' },
  { label: __('Individual owner'), value: 'owner' },
]

const targets = createResource({
  url: 'crm.api.student_ownership.get_eligible_ownership_targets',
  makeParams: () => ({ student: props.student }),
  auto: false,
  initialData: { owners: [], pools: [] },
})
const targetOptions = computed(() => {
  const items = targetKind.value === 'owner' ? targets.data?.owners : targets.data?.pools
  return (items || []).map((item) => ({ label: item.label || item.name, value: item.name || item.id }))
})
const selectedTarget = computed(() => {
  const items = targetKind.value === 'owner' ? targets.data?.owners : targets.data?.pools
  return (items || []).find((item) => (item.name || item.id) === targetId.value)
})
const canSubmit = computed(() => Boolean(targetId.value && reason.value.trim() && !targets.loading))

watch(show, (open) => {
  if (open) {
    targetId.value = ''
    reason.value = ''
    error.value = ''
    targets.reload()
  }
}, { immediate: true })
watch(targetKind, () => (targetId.value = ''))

function resetError() {
  error.value = ''
}

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const response = await call(
      'crm.api.student_ownership.change_student_ownership',
      buildOwnershipPayload({
        student: props.student,
        target: {
          kind: targetKind.value,
          id: targetId.value,
          teamId: selectedTarget.value?.team,
        },
        reason: reason.value,
        revision: props.ownership.revision,
        idempotencyKey: createCommandId(),
        correlationId: createCommandId(),
      }),
    )
    toast.success(__('Student ownership updated.'))
    emit('changed', response)
    show.value = false
  } catch (err) {
    if (isStaleOwnershipError(err)) {
      error.value = __('This ownership changed while you were editing. Reload it and review the current state before trying again.')
      emit('refresh-required')
    } else {
      error.value = safeCommandError(err, __('Unable to change ownership.'))
    }
  } finally {
    loading.value = false
  }
}
</script>
