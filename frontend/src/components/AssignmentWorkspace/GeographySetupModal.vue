<template>
  <Dialog
    v-model="show"
    :options="{ title: dialogTitle, size: 'lg' }"
    @close="reset"
  >
    <template #body-content>
      <div class="space-y-4" data-testid="geography-setup-modal">
        <p
          class="rounded-lg border border-blue-100 bg-blue-50/60 p-3 text-sm text-blue-900"
        >
          {{ helperText }}
        </p>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl
            v-model="name"
            :label="nameLabel"
            :disabled="submitting"
            required
          />
          <FormControl
            v-model="code"
            :label="kind === 'cluster' ? __('Mã cụm') : __('Mã khu vực')"
            :disabled="submitting"
          />
          <FormControl
            v-if="kind === 'cluster'"
            v-model="province"
            type="select"
            :label="__('Tỉnh/TP')"
            :options="provinceOptions"
            :disabled="submitting"
            required
          />
          <FormControl
            v-else
            v-model="cluster"
            type="select"
            :label="__('Cụm')"
            :options="clusterOptions"
            :disabled="submitting"
            required
          />
        </div>
        <label
          v-if="isCluster"
          class="flex items-center gap-2 text-sm text-ink-gray-8"
        >
          <input v-model="isActive" type="checkbox" :disabled="submitting" />
          {{ __('Cụm đang hoạt động') }}
        </label>
        <p
          v-if="error"
          class="rounded-md bg-red-50 p-3 text-sm text-red-900"
          role="alert"
        >
          {{ error }}
        </p>
      </div>
    </template>
    <template #actions>
      <div class="flex w-full justify-end gap-2">
        <Button
          :label="__('Hủy')"
          :disabled="submitting"
          @click="show = false"
        />
        <Button
          variant="solid"
          :label="kind === 'cluster' ? __('Tạo cụm') : __('Tạo khu vực')"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="submit"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, FormControl, call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { createCommandId, safeCommandError } from '@/utils/studentOwnership'

const props = defineProps({
  kind: { type: String, default: 'cluster' },
  options: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['saved'])
const show = defineModel({ type: Boolean })

const name = ref('')
const code = ref('')
const province = ref('')
const cluster = ref('')
const isActive = ref(true)
const error = ref('')
const submitting = ref(false)

const isCluster = computed(() => props.kind === 'cluster')
const dialogTitle = computed(() =>
  isCluster.value ? __('Tạo cụm') : __('Tạo khu vực'),
)
const nameLabel = computed(() =>
  isCluster.value ? __('Tên cụm') : __('Tên khu vực'),
)
const helperText = computed(() =>
  isCluster.value
    ? __('Cụm gom các khu vực trong cùng một Tỉnh/TP.')
    : __(
        'Khu vực là phạm vi nhỏ hơn cụm. Tạo xong, bạn có thể gán khu vực vào một nhóm tư vấn.',
      ),
)
const provinceOptions = computed(() => props.options?.provinces || [])
const clusterOptions = computed(() =>
  (props.options?.clusters || []).filter((item) => item.is_active),
)
const canSubmit = computed(() =>
  Boolean(
    name.value.trim() &&
    (isCluster.value ? province.value : cluster.value) &&
    !submitting.value,
  ),
)

watch(show, (open) => {
  if (open) resetForm()
})

function resetForm() {
  name.value = ''
  code.value = ''
  province.value = provinceOptions.value[0]?.value || ''
  cluster.value = clusterOptions.value[0]?.value || ''
  isActive.value = true
  error.value = ''
}

function reset() {
  error.value = ''
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    const action = isCluster.value ? 'create_cluster' : 'create_zone'
    const response = await call(
      'crm.api.assignment_workspace.create_setup_reference',
      {
        action,
        name: name.value.trim(),
        code: code.value.trim() || undefined,
        province: isCluster.value ? province.value : undefined,
        cluster: isCluster.value ? undefined : cluster.value,
        is_active: isCluster.value ? isActive.value : undefined,
        reason: isCluster.value
          ? `Tạo cụm ${name.value.trim()} từ màn hình Thiết lập phân bổ Lead.`
          : `Tạo khu vực ${name.value.trim()} từ màn hình Thiết lập phân bổ Lead.`,
        idempotency_key: createCommandId(),
        correlation_id: createCommandId(),
      },
    )
    toast.success(isCluster.value ? __('Đã tạo cụm.') : __('Đã tạo khu vực.'))
    emit('saved', response)
    show.value = false
  } catch (requestError) {
    error.value = safeCommandError(
      requestError,
      isCluster.value ? __('Không thể tạo cụm.') : __('Không thể tạo khu vực.'),
    )
  } finally {
    submitting.value = false
  }
}
</script>
