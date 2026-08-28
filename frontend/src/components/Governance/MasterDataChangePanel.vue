<template>
  <section class="rounded border border-outline-gray-modals bg-surface-modal p-4" :aria-label="__('Governance controls for {0}', [record.name])">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="font-medium text-ink-gray-8">{{ __('Governed reference value') }}</p>
        <p class="mt-1 text-sm text-ink-gray-6">
          {{ __('Version {0} · {1}', [record.version || 1, record.approval_state || __('Current')]) }}
        </p>
      </div>
      <p class="max-w-sm text-sm text-ink-gray-6">
        {{ __('Changes create an immutable proposal. The server checks authority and approval requirements.') }}
      </p>
    </div>

    <div class="mt-4 flex flex-wrap gap-2">
      <Button :label="__('Supersede')" :disabled="!affordances.canPropose" @click="openProposal('Supersede')" />
      <Button :label="__('Retire')" theme="red" :disabled="!affordances.canPropose || record.approval_state === 'Retired'" @click="openProposal('Retire')" />
      <Button :label="__('Reactivate')" :disabled="!affordances.canPropose || record.approval_state !== 'Retired'" @click="openProposal('Reactivate')" />
    </div>
    <p v-if="!affordances.canPropose" class="mt-2 text-xs text-ink-gray-5">
      {{ __('Only {0} can propose a change. Your access is confirmed by the server when you submit.', [affordances.ownerRole]) }}
    </p>

    <div v-if="pendingChange.name" class="mt-4 rounded bg-surface-amber-1 p-3 text-sm" aria-live="polite">
      <p class="font-medium text-ink-gray-8">{{ __('Pending {0} request', [pendingChange.action]) }}</p>
      <p class="mt-1 text-ink-gray-6">{{ pendingChange.reason }}</p>
      <p class="mt-1 text-xs text-ink-gray-5">{{ __('Approvals: {0} / {1}', [pendingChange.approvedRoles?.join(', ') || __('none'), pendingChange.requiredApproverRoles?.join(', ') || __('none')]) }}</p>
      <div v-if="affordances.canApprove" class="mt-2 flex gap-2">
        <Button size="sm" variant="solid" :label="__('Approve')" :loading="approving" @click="approvePending" />
        <Button size="sm" theme="red" :label="__('Reject')" :loading="approving" @click="rejectPending" />
      </div>
    </div>

    <div v-if="impact.entries.length" class="mt-4 rounded bg-surface-gray-1 p-3 text-sm" aria-live="polite">
      <p class="font-medium text-ink-gray-8">{{ __('Impact preview · {0} references', [impact.total]) }}</p>
      <ul class="mt-1 list-disc pl-5 text-ink-gray-6">
        <li v-for="item in impact.entries" :key="item.reference">{{ item.reference }}: {{ item.count }}</li>
      </ul>
    </div>
    <p v-if="error" class="mt-3 text-sm text-ink-red-3" role="alert">{{ error }}</p>

    <Dialog v-model="show" :options="{ title: dialogTitle }" @close="reset">
      <template #body-content>
        <div class="space-y-4">
          <p class="text-sm text-ink-gray-6">{{ __('Retirement blocks new references while keeping historical records intact.') }}</p>
          <FormControl v-if="action === 'Supersede'" v-model="newValue" :label="__('Successor value')" required autofocus />
          <FormControl v-model="reason" type="textarea" :label="__('Reason')" :description="__('This becomes part of the immutable request record.')" required />
          <p v-if="dialogError" class="text-sm text-ink-red-3" role="alert">{{ dialogError }}</p>
        </div>
      </template>
      <template #actions>
        <div class="flex justify-end gap-2">
          <Button :label="__('Cancel')" :disabled="submitting" @click="show = false" />
          <Button variant="solid" :label="__('Submit proposal')" :loading="submitting" :disabled="!canSubmit" @click="submitProposal" />
        </div>
      </template>
    </Dialog>
  </section>
</template>

<script setup>
import { governanceAuditApi, buildProposalPayload, createGovernanceCommandId, governanceAffordances, governanceErrorState, normalizeImpact, normalizeChange } from '@/utils/governanceAudit'
import { usersStore } from '@/stores/users'
import { Button, Dialog, FormControl, call, toast } from 'frappe-ui'
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  record: { type: Object, required: true },
})
const emit = defineEmits(['proposed'])
const { getCurrentUser } = usersStore()
const show = ref(false)
const action = ref('')
const newValue = ref('')
const reason = ref('')
const error = ref('')
const dialogError = ref('')
const submitting = ref(false)
const impact = ref({ entries: [], total: 0 })
const pendingChange = ref({})
const approving = ref(false)
const commandId = ref(createGovernanceCommandId())
const affordances = computed(() => governanceAffordances(getCurrentUser(), props.doctype))
const dialogTitle = computed(() => action.value ? __('Propose {0}', [action.value.toLowerCase()]) : __('Propose change'))
const canSubmit = computed(() => !submitting.value && reason.value.trim() && (action.value !== 'Supersede' || newValue.value.trim()))

async function loadPending() {
  try {
    pendingChange.value = normalizeChange(await call(governanceAuditApi.getPendingChange, { doctype: props.doctype, docname: props.record.name }))
  } catch {
    pendingChange.value = {}
  }
}

onMounted(loadPending)

async function openProposal(nextAction) {
  action.value = nextAction
  error.value = ''
  dialogError.value = ''
  impact.value = { entries: [], total: 0 }
  commandId.value = createGovernanceCommandId()
  show.value = true
  try {
    impact.value = normalizeImpact(await call(governanceAuditApi.checkImpact, { doctype: props.doctype, docname: props.record.name }))
  } catch (requestError) {
    error.value = governanceErrorState(requestError).message
  }
}

async function submitProposal() {
  if (!canSubmit.value || !affordances.value.canPropose) return
  submitting.value = true
  dialogError.value = ''
  try {
    const change = await call(governanceAuditApi.proposeChange, buildProposalPayload({
      doctype: props.doctype, docname: props.record.name, action: action.value, newValue: newValue.value,
      reason: reason.value, idempotencyKey: commandId.value, expectedVersion: props.record.version,
    }))
    toast.success(__('Governance proposal submitted.'))
    emit('proposed', change)
    await loadPending()
    show.value = false
  } catch (requestError) {
    dialogError.value = governanceErrorState(requestError).message
  } finally {
    submitting.value = false
  }
}

async function approvePending() {
  if (!pendingChange.value.name || approving.value) return
  approving.value = true
  try {
    await call(governanceAuditApi.approveChange, { change_log_name: pendingChange.value.name })
    toast.success(__('Governance proposal approved.'))
    await loadPending()
    emit('proposed')
  } catch (requestError) {
    error.value = governanceErrorState(requestError).message
  } finally {
    approving.value = false
  }
}

async function rejectPending() {
  if (!pendingChange.value.name || approving.value) return
  approving.value = true
  try {
    await call(governanceAuditApi.rejectChange, {
      change_log_name: pendingChange.value.name,
      reason: __('Rejected from governance panel'),
    })
    toast.success(__('Governance proposal rejected.'))
    await loadPending()
    emit('proposed')
  } catch (requestError) {
    error.value = governanceErrorState(requestError).message
  } finally {
    approving.value = false
  }
}

function reset() {
  action.value = ''
  newValue.value = ''
  reason.value = ''
  dialogError.value = ''
}
</script>
