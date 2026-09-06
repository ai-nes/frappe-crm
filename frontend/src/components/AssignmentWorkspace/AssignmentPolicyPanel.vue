<template>
  <section class="space-y-4" data-testid="assignment-policies">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="text-xs font-semibold uppercase tracking-wide text-ink-gray-5">{{ __('Chính sách phân bổ') }}</p>
        <h2 class="mt-1 text-xl font-semibold text-ink-gray-9">{{ __('Mỗi Pool chọn Sale theo cách nào?') }}</h2>
        <p class="mt-1 text-sm text-ink-gray-6">{{ __('Policy xác định phạm vi, chiến lược và thời gian hiệu lực. Policy active đã phê duyệt sẽ được dùng cho Lead mới.') }}</p>
      </div>
      <Button v-if="canManage" variant="solid" size="sm" :label="__('Tạo policy phiên bản mới')" iconLeft="plus" @click="showCreate = true" />
    </div>

    <div class="overflow-x-auto rounded-xl border border-outline-gray-2 bg-surface-white shadow-sm">
      <table class="w-full min-w-[960px] text-sm">
        <thead class="bg-surface-gray-1 text-left text-xs text-ink-gray-6">
          <tr><th class="px-4 py-3">{{ __('Policy / phạm vi') }}</th><th class="px-4 py-3">{{ __('Chiến lược') }}</th><th class="px-4 py-3">{{ __('Hiệu lực') }}</th><th class="px-4 py-3">{{ __('Trạng thái') }}</th><th class="px-4 py-3 text-right">{{ __('Thao tác') }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="policy in policies" :key="policy.name" class="border-t border-outline-gray-1">
            <td class="px-4 py-3"><p class="font-medium text-ink-gray-9">{{ policy.policy_key }}</p><p class="mt-0.5 text-xs text-ink-gray-5">{{ policy.campus }} · {{ policy.student_pool }} · v{{ policy.policy_version }}</p></td>
            <td class="px-4 py-3"><Badge :label="policyLabel(policy.strategy)" theme="blue" variant="subtle" /></td>
            <td class="px-4 py-3 text-xs text-ink-gray-6">{{ formatDate(policy.effective_from) }} → {{ formatDate(policy.effective_until) }}</td>
            <td class="px-4 py-3"><Badge :label="statusLabel(policy.status)" :theme="statusTheme(policy.status)" variant="subtle" /></td>
            <td class="px-4 py-3 text-right">
              <Button v-if="policy.status === 'draft' && canApprove" size="sm" variant="subtle" :label="__('Phê duyệt')" :loading="approving === policy.name" @click="approve(policy)" />
              <span v-else class="text-xs text-ink-gray-5">{{ policy.status === 'active' ? __('Đang sử dụng') : __('Đã lưu') }}</span>
            </td>
          </tr>
          <tr v-if="!policies.length"><td colspan="5" class="px-4 py-10 text-center text-sm text-ink-gray-5">{{ __('Chưa có policy trong phạm vi này.') }}</td></tr>
        </tbody>
      </table>
    </div>

    <Dialog v-model="showCreate" :options="{ size: 'lg' }">
      <template #body-title><h3 class="text-lg font-semibold text-ink-gray-9">{{ __('Tạo policy phân bổ') }}</h3></template>
      <template #body-content>
        <div class="space-y-4">
          <p class="rounded-md border border-blue-100 bg-blue-50/60 p-3 text-sm text-blue-900">{{ __('Policy mới bắt đầu ở trạng thái nháp. Một người có quyền Admissions Director cần phê duyệt trước khi dùng.') }}</p>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl v-model="draft.policy_key" :label="__('Mã policy')" :placeholder="__('route-hcm-khu-dong-v2')" />
            <FormControl v-model="draft.policy_version" type="number" :label="__('Phiên bản')" min="1" />
            <FormControl v-model="draft.campus" type="select" :label="__('Campus')" :options="campusOptions" />
            <FormControl v-model="draft.student_pool" type="select" :label="__('Pool tiếp nhận')" :options="poolOptions" />
            <FormControl v-model="draft.strategy" type="select" :label="__('Chiến lược')" :options="strategyOptions" />
            <FormControl v-model="draft.effective_from" type="date" :label="__('Có hiệu lực từ')" />
          </div>
          <FormControl v-model="draft.scoring_weights" type="textarea" :label="__('Trọng số weighted score (JSON)')" :disabled="draft.strategy !== 'weighted_score'" />
        </div>
      </template>
      <template #actions>
        <div class="flex justify-end gap-2"><Button variant="ghost" :label="__('Huỷ')" @click="showCreate = false" /><Button variant="solid" :label="__('Lưu bản nháp')" :loading="creating" :disabled="!canCreate" @click="createPolicy" /></div>
      </template>
    </Dialog>
  </section>
</template>

<script setup>
import { Badge, Button, Dialog, FormControl, createResource, toast } from 'frappe-ui'
import { computed, ref } from 'vue'
import { assignmentWorkspacePolicyLabel } from '@/data/assignmentWorkspace'

const props = defineProps({
  policies: { type: Array, default: () => [] },
  options: { type: Object, default: () => ({ campuses: [], pools: [] }) },
  canManage: Boolean,
  canApprove: Boolean,
})
const emit = defineEmits(['changed'])
const showCreate = ref(false)
const creating = ref(false)
const approving = ref('')
const draft = ref({ policy_key: '', policy_version: 1, campus: '', student_pool: '', strategy: 'round_robin', effective_from: new Date().toISOString().slice(0, 10), scoring_weights: '{"load":0.35,"territory":0.30,"performance":0.20,"rotation":0.15}' })
const policyCreate = createResource({ url: 'crm.api.student_policy.create_student_policy', method: 'POST' })
const policyApprove = createResource({ url: 'crm.api.student_policy.approve_student_policy', method: 'POST' })
const campusOptions = computed(() => (props.options.campuses || []).map((item) => ({ label: item.label, value: item.value })))
const poolOptions = computed(() => (props.options.pools || []).filter((item) => !draft.value.campus || item.campus === draft.value.campus).map((item) => ({ label: item.label, value: item.value })))
const strategyOptions = [{ label: __('Luân phiên công bằng'), value: 'round_robin' }, { label: __('Chấm điểm có trọng số'), value: 'weighted_score' }]
const canCreate = computed(() => draft.value.policy_key && draft.value.campus && draft.value.student_pool && draft.value.effective_from)

function policyLabel(strategy) { return assignmentWorkspacePolicyLabel(strategy) }
function statusLabel(status) { return { draft: __('Bản nháp'), active: __('Đang hiệu lực'), retired: __('Đã ngưng') }[status] || status }
function statusTheme(status) { return { draft: 'orange', active: 'green', retired: 'gray' }[status] || 'gray' }
function formatDate(value) { return value ? String(value).slice(0, 10) : __('Không giới hạn') }

async function createPolicy() {
  creating.value = true
  try {
    await policyCreate.submit({ doctype: 'CRM Student Routing Policy', values: { ...draft.value } })
    toast.success(__('Đã lưu policy nháp.'))
    showCreate.value = false
    emit('changed')
  } catch (error) { toast.error(error?.messages?.[0] || __('Không thể tạo policy.')) }
  finally { creating.value = false }
}

async function approve(policy) {
  approving.value = policy.name
  try {
    await policyApprove.submit({ doctype: 'CRM Student Routing Policy', name: policy.name })
    toast.success(__('Đã phê duyệt policy.'))
    emit('changed')
  } catch (error) { toast.error(error?.messages?.[0] || __('Không thể phê duyệt policy.')) }
  finally { approving.value = '' }
}
</script>
