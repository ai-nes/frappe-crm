<template>
  <Dialog v-model="show" :options="{ title: __('Record student outcome') }">
    <template #body-content>
      <div class="space-y-4">
        <FormControl v-model="outcome" type="select" :label="__('Outcome')" :options="outcomeOptions" required />
        <FormControl v-model="continuity" type="select" :label="__('Continuity')" :options="continuityOptions" required />
        <template v-if="continuity === 'task'">
          <FormControl v-model="taskTitle" :label="__('Next action')" required />
          <FormControl v-model="assignee" :label="__('Assignee')" required />
          <FormControl v-model="dueAt" type="datetime-local" :label="__('Due date')" required />
        </template>
        <FormControl v-if="continuity === 'waiting'" v-model="expiresAt" type="datetime-local" :label="__('Waiting until')" required />
        <FormControl v-model="reason" type="textarea" :label="__('Reason / waiting context')" :required="continuity !== 'task'" />
        <FormControl v-model="evidence" type="textarea" :label="__('Evidence references')" :description="__('Use outcome IDs or category:doctype:name references, separated by commas.')" />
      </div>
      <ErrorMessage v-if="error" class="mt-4" :message="error" role="alert" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="loading" @click="show = false" />
        <Button variant="solid" :label="__('Record outcome')" :loading="loading" :disabled="!canSubmit" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { createStudentEngagementCommandId, safeLifecycleError } from '@/utils/studentEngagement'

const props = defineProps({
  student: { type: String, required: true },
  context: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['changed', 'refresh-required'])
const show = defineModel({ type: Boolean })
const outcome = ref('connected')
const continuity = ref('task')
const taskTitle = ref('')
const assignee = ref('')
const dueAt = ref('')
const expiresAt = ref('')
const reason = ref('')
const evidence = ref('')
const error = ref('')
const loading = ref(false)
const commandKey = ref(createStudentEngagementCommandId())
const outcomeOptions = ['connected', 'qualified', 'follow_up_required', 'no_response', 'not_interested', 'invalid', 'completed']
const continuityOptions = ['task', 'waiting', 'terminal']
const canSubmit = computed(() => !loading.value && outcome.value && continuity.value && (continuity.value === 'task' ? taskTitle.value && assignee.value && dueAt.value : continuity.value === 'waiting' ? reason.value.trim() && expiresAt.value : reason.value.trim()))

watch(show, (open) => {
  if (!open) return
  error.value = ''
  commandKey.value = createStudentEngagementCommandId()
  if (!taskTitle.value) taskTitle.value = __('Follow up with student')
})

async function submit() {
  if (!canSubmit.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await call('crm.api.student_engagement.record_student_outcome', {
      student: props.student,
      interaction: props.context?.latest_interaction?.name,
      outcome_code: outcome.value,
      continuity_kind: continuity.value,
      next_action: continuity.value === 'task' ? { title: taskTitle.value, student: props.student } : null,
      next_action_assignee: assignee.value,
      next_action_due_at: dueAt.value,
      continuity_reason: reason.value,
      continuity_expires_at: continuity.value === 'waiting' ? expiresAt.value : null,
      qualification_evidence: evidence.value,
      expected_revision: props.context?.engagement_revision ?? props.context?.revision ?? 0,
      idempotency_key: commandKey.value,
      correlation_id: commandKey.value,
    })
    toast.success(__('Student outcome recorded.'))
    emit('changed', response)
    show.value = false
  } catch (err) {
    error.value = safeLifecycleError(err, __('Unable to record the Student outcome.'))
    if ([409, 412].includes(err?.httpStatusCode || err?.status)) emit('refresh-required')
  } finally {
    loading.value = false
  }
}
</script>
