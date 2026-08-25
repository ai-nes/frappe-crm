<template>
  <section v-if="items.length" class="mb-4 rounded border border-outline-gray-modals bg-surface-modal p-3" :aria-label="__('Pending governance requests')">
    <p class="font-medium text-ink-gray-8">{{ __('Pending governance requests') }}</p>
    <div v-for="item in items" :key="item.name" class="mt-3 border-t pt-3 text-sm">
      <p class="font-medium">{{ item.action }} · {{ item.new_value || item.reference_docname }}</p>
      <p class="text-ink-gray-6">{{ item.reason }}</p>
      <p class="text-xs text-ink-gray-5">{{ __('Approvals: {0} / {1}', [item.approved_by_roles || __('none'), item.required_approver_roles || __('none')]) }}</p>
      <div class="mt-2 flex gap-2">
        <Button size="sm" variant="solid" :label="__('Approve')" :loading="busy === item.name" @click="decide(item, 'approve')" />
        <Button size="sm" theme="red" :label="__('Reject')" :loading="busy === item.name" @click="decide(item, 'reject')" />
      </div>
    </div>
  </section>
</template>

<script setup>
import { governanceAuditApi, governanceErrorState } from '@/utils/governanceAudit'
import { Button, call, toast } from 'frappe-ui'
import { onMounted, ref } from 'vue'

const props = defineProps({ doctype: { type: String, required: true } })
const emit = defineEmits(['decided'])
const items = ref([])
const busy = ref('')

async function reload() {
  try {
    items.value = await call(governanceAuditApi.listPendingChanges, { doctype: props.doctype }) || []
  } catch {
    items.value = []
  }
}

async function decide(item, decision) {
  busy.value = item.name
  try {
    if (decision === 'approve') {
      await call(governanceAuditApi.approveChange, { change_log_name: item.name })
    } else {
      await call(governanceAuditApi.rejectChange, { change_log_name: item.name, reason: __('Rejected from approval queue') })
    }
    toast.success(decision === 'approve' ? __('Governance proposal approved.') : __('Governance proposal rejected.'))
    await reload()
    emit('decided')
  } catch (error) {
    toast.error(governanceErrorState(error).message)
  } finally {
    busy.value = ''
  }
}

onMounted(reload)
</script>
