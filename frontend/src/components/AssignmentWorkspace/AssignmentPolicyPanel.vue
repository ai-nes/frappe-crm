<template>
  <section class="space-y-4" data-testid="assignment-policies">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="mt-1 text-xl font-semibold text-ink-gray-9">
          {{ __('Cách chia Lead') }}
        </h2>
        <p class="mt-1 text-sm text-ink-gray-6">
          {{ __('Chọn cách hệ thống chia Lead cho nhóm tư vấn.') }}
        </p>
      </div>
      <Button
        v-if="canManage"
        variant="solid"
        size="sm"
        :label="__('Tạo cách chia Lead')"
        iconLeft="plus"
        @click="openCreate"
      />
    </div>

    <div
      class="rounded-xl border border-blue-100 bg-blue-50/60 px-4 py-3 text-sm text-blue-900"
    >
      <p class="font-medium">{{ __('Luồng xử lý') }}</p>
      <p class="mt-1 text-blue-800">
        {{ __('Lead mới → hàng chờ → cách phân công → nhân viên tư vấn.') }}
      </p>
    </div>

    <div
      class="overflow-x-auto rounded-xl border border-outline-gray-2 bg-surface-white shadow-sm"
    >
      <table class="w-full min-w-[960px] text-sm">
        <thead class="bg-surface-gray-1 text-left text-xs text-ink-gray-6">
          <tr>
            <th class="px-4 py-3">{{ __('Hàng chờ') }}</th>
            <th class="px-4 py-3">{{ __('Cách chia') }}</th>
            <th class="px-4 py-3">{{ __('Thời gian dùng') }}</th>
            <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Thao tác') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="policy in policies"
            :key="policy.name"
            class="border-t border-outline-gray-1"
          >
            <td class="px-4 py-3">
              <p class="font-medium text-ink-gray-9">
                {{ poolLabel(policy.student_pool) }}
              </p>
              <p class="mt-0.5 text-xs text-ink-gray-5">
                {{ campusLabel(policy.campus) }}
              </p>
            </td>
            <td class="px-4 py-3">
              <Badge
                :label="policyLabel(policy.strategy)"
                theme="blue"
                variant="subtle"
              />
              <p class="mt-1 max-w-xs text-xs text-ink-gray-5">
                {{ policyDescription(policy.strategy) }}
              </p>
            </td>
            <td class="px-4 py-3 text-xs text-ink-gray-6">
              <p>{{ __('Từ') }} {{ formatDate(policy.effective_from) }}</p>
              <p v-if="policy.effective_until">
                {{ __('Đến') }} {{ formatDate(policy.effective_until) }}
              </p>
              <p v-else class="text-ink-gray-5">{{ __('Không giới hạn') }}</p>
            </td>
            <td class="px-4 py-3">
              <Badge
                :label="statusLabel(policy.status)"
                :theme="statusTheme(policy.status)"
                variant="subtle"
              />
            </td>
            <td class="px-4 py-3 text-right">
              <Button
                v-if="policy.status === 'draft' && canApprove"
                size="sm"
                variant="subtle"
                :label="__('Duyệt dùng')"
                :loading="approving === policy.name"
                @click="approve(policy)"
              />
              <span v-else class="text-xs text-ink-gray-5">
                {{
                  policy.status === 'active' ? __('Đang dùng') : __('Đã dừng')
                }}
              </span>
            </td>
          </tr>
          <tr v-if="!policies.length">
            <td
              colspan="5"
              class="px-4 py-10 text-center text-sm text-ink-gray-5"
            >
              {{ __('Chưa có policy trong phạm vi này.') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Dialog v-model="showCreate" :options="{ size: 'lg' }">
      <template #body-title
        ><h3 class="text-lg font-semibold text-ink-gray-9">
          {{ __('Tạo cách chia Lead') }}
        </h3></template
      >
      <template #body-content>
        <div class="space-y-4">
          <p
            class="rounded-md border border-blue-100 bg-blue-50/60 p-3 text-sm text-blue-900"
          >
            {{
              __(
                'Sau khi lưu, người có quyền duyệt sẽ kiểm tra trước khi đưa vào sử dụng.',
              )
            }}
          </p>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl
              v-model="draft.campus"
              type="select"
              :label="__('Cơ sở')"
              :options="campusOptions"
              @update:model-value="draft.student_pool = ''"
            />
            <FormControl
              v-model="draft.student_pool"
              type="select"
              :label="__('Hàng chờ Lead')"
              :options="poolOptions"
            />
            <FormControl
              v-model="draft.strategy"
              type="select"
              :label="__('Cách chia')"
              :options="strategyOptions"
            />
            <FormControl
              v-model="draft.effective_from"
              type="date"
              :label="__('Bắt đầu dùng từ')"
            />
          </div>
          <div
            class="rounded-md bg-surface-gray-1 px-3 py-2 text-sm text-ink-gray-6"
          >
            {{ policyDescription(draft.strategy) }}
          </div>
        </div>
      </template>
      <template #actions>
        <div class="flex justify-end gap-2">
          <Button
            variant="ghost"
            :label="__('Huỷ')"
            @click="showCreate = false"
          /><Button
            variant="solid"
            :label="__('Lưu bản nháp')"
            :loading="creating"
            :disabled="!canCreate"
            @click="createPolicy"
          />
        </div>
      </template>
    </Dialog>
  </section>
</template>

<script setup>
import {
  Badge,
  Button,
  Dialog,
  FormControl,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, ref } from 'vue'
import {
  assignmentWorkspacePolicyDescription,
  assignmentWorkspacePolicyLabel,
} from '@/data/assignmentWorkspace'

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
const draft = ref({
  policy_version: 1,
  campus: '',
  student_pool: '',
  strategy: 'round_robin',
  effective_from: new Date().toISOString().slice(0, 10),
  scoring_weights:
    '{"load":0.35,"territory":0.30,"performance":0.20,"rotation":0.15}',
})
const policyCreate = createResource({
  url: 'crm.api.student_policy.create_student_policy',
  method: 'POST',
})
const policyApprove = createResource({
  url: 'crm.api.student_policy.approve_student_policy',
  method: 'POST',
})
const campusOptions = computed(() =>
  (props.options.campuses || []).map((item) => ({
    label: item.label,
    value: item.value,
  })),
)
const poolOptions = computed(() =>
  (props.options.pools || [])
    .filter((item) => !draft.value.campus || item.campus === draft.value.campus)
    .map((item) => ({
      label: humanPoolLabel(item.label),
      value: item.value,
    })),
)
const strategyOptions = [
  { label: __('Chia đều lần lượt'), value: 'round_robin' },
  { label: __('Ưu tiên người phù hợp'), value: 'weighted_score' },
]
const canCreate = computed(
  () =>
    draft.value.campus &&
    draft.value.student_pool &&
    draft.value.effective_from,
)

function policyLabel(strategy) {
  return assignmentWorkspacePolicyLabel(strategy)
}
function policyDescription(strategy) {
  return assignmentWorkspacePolicyDescription(strategy)
}
function optionLabel(options, value) {
  return options.find((item) => item.value === value)?.label || 'Chưa xác định'
}
function humanPoolLabel(value) {
  const raw = String(value || 'Chưa xác định').trim()
  const cleaned = raw
    .replace(/^crm-[^-]+-(?:showcase-)?/i, '')
    .replace(/-routing-v\d+$/i, '')
    .replace(/-v\d+$/i, '')
  const match = cleaned.match(/^pool-(lead|ctv)(?:-(.*))?$/i)
  if (match) {
    const kind = match[1].toLowerCase() === 'ctv' ? 'CTV' : 'Lead'
    const scope = formatPoolScope(match[2])
    return scope ? `Hàng chờ ${kind} · ${scope}` : `Hàng chờ ${kind}`
  }
  return raw
    .replace(/^Pool Lead\b/i, 'Hàng chờ Lead')
    .replace(/^Pool CTV\b/i, 'Hàng chờ CTV')
    .replace(/^Pool\b/i, 'Hàng chờ')
}

function formatPoolScope(value) {
  if (!value) return ''
  return value
    .replace(/[-_]+/g, ' ')
    .replace(/\bfptu\b/gi, 'FPTU')
    .replace(/\btp hcm\b/gi, 'TP.HCM')
    .replace(/\bkhu ng\b/gi, 'Khu Đông')
    .replace(/\bkhu trung tam\b/gi, 'Khu trung tâm')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}
function campusLabel(value) {
  return optionLabel(campusOptions.value, value)
}
function poolLabel(value) {
  return optionLabel(poolOptionsForDisplay.value, value)
}
function statusLabel(status) {
  return (
    {
      draft: __('Chờ duyệt'),
      active: __('Đang dùng'),
      retired: __('Đã dừng'),
    }[status] || __('Chưa xác định')
  )
}
function statusTheme(status) {
  return { draft: 'orange', active: 'green', retired: 'gray' }[status] || 'gray'
}
function formatDate(value) {
  return value ? String(value).slice(0, 10) : ''
}

const poolOptionsForDisplay = computed(() =>
  (props.options.pools || []).map((item) => ({
    label: humanPoolLabel(item.label),
    value: item.value,
  })),
)

function slug(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/đ/g, 'd')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

function nextVersion(campus, pool) {
  const versions = props.policies
    .filter((item) => item.campus === campus && item.student_pool === pool)
    .map((item) => Number(item.policy_version) || 0)
  return Math.max(0, ...versions) + 1
}

function openCreate() {
  draft.value = {
    policy_version: 1,
    campus: '',
    student_pool: '',
    strategy: 'round_robin',
    effective_from: new Date().toISOString().slice(0, 10),
    scoring_weights:
      '{"load":0.35,"territory":0.30,"performance":0.20,"rotation":0.15}',
  }
  showCreate.value = true
}

async function createPolicy() {
  creating.value = true
  try {
    const version = nextVersion(draft.value.campus, draft.value.student_pool)
    const values = {
      ...draft.value,
      policy_version: version,
      policy_key: `assignment-${slug(campusLabel(draft.value.campus))}-${slug(poolLabel(draft.value.student_pool))}-v${version}-${Date.now()}`,
    }
    await policyCreate.submit({
      doctype: 'CRM Student Routing Policy',
      values,
    })
    toast.success(__('Đã lưu cách phân công.'))
    showCreate.value = false
    emit('changed')
  } catch (error) {
    toast.error(error?.messages?.[0] || __('Không thể lưu cách phân công.'))
  } finally {
    creating.value = false
  }
}

async function approve(policy) {
  approving.value = policy.name
  try {
    await policyApprove.submit({
      doctype: 'CRM Student Routing Policy',
      name: policy.name,
    })
    toast.success(__('Đã đưa cách phân công vào sử dụng.'))
    emit('changed')
  } catch (error) {
    toast.error(error?.messages?.[0] || __('Không thể duyệt cách phân công.'))
  } finally {
    approving.value = ''
  }
}
</script>
