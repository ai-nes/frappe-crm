<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 shadow-sm">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div>
        <h2 class="font-semibold text-ink-gray-9">{{ __('Bộ lọc phân bổ') }}</h2>
        <p class="mt-0.5 text-xs text-ink-gray-5">
          {{ __('Lọc theo đúng phạm vi mà tài khoản hiện tại được phép xem.') }}
        </p>
      </div>
      <Button
        variant="subtle"
        size="sm"
        :label="__('Xoá bộ lọc')"
        iconLeft="x"
        @click="$emit('reset')"
      />
    </div>
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      <FormControl
        v-model="local.search"
        :label="__('Tìm kiếm')"
        :placeholder="__('Tên trường, team, nhân viên...')"
        @update:modelValue="change('search', $event)"
      />
      <FormControl
        v-for="field in selectFields"
        :key="field.key"
        v-model="local[field.key]"
        type="select"
        :label="__(field.label)"
        :options="field.options"
        @update:modelValue="change(field.key, $event)"
      />
    </div>
    <button
      type="button"
      class="mt-3 inline-flex items-center gap-1.5 rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-sm font-medium text-orange-800 hover:bg-orange-100 focus:outline-none focus:ring-2 focus:ring-orange-300"
      @click="setUnconfigured"
    >
      <FeatherIcon name="alert-circle" class="size-4" aria-hidden="true" />
      {{ __('Chỉ xem phần chưa cấu hình') }}
    </button>
  </section>
</template>

<script setup>
import { Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, reactive, watch } from 'vue'
import {
  assignmentWorkspaceStatusLabel,
  assignmentWorkspaceWorkloadLabel,
} from '@/data/assignmentWorkspace'

const props = defineProps({
  schema: { type: Object, default: () => ({ fields: [] }) },
  modelValue: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['update:modelValue', 'change', 'reset'])
const local = reactive({ ...props.modelValue })

watch(
  () => props.modelValue,
  (value) => Object.assign(local, value || {}),
  { deep: true },
)

const selectFields = computed(() =>
  (props.schema?.fields || [])
    .filter((field) => ['status', 'workload', 'campus', 'province', 'cluster', 'zone', 'school', 'team', 'staff'].includes(field.key))
    .map((field) => ({
      ...field,
      options: [
        { label: __('Tất cả'), value: 'all' },
        ...(field.options || []).map((option) => ({
          ...option,
          label:
            field.key === 'status'
              ? assignmentWorkspaceStatusLabel(option.label)
              : field.key === 'workload'
                ? assignmentWorkspaceWorkloadLabel(option.label)
                : option.label,
        })),
      ],
    })),
)

function change(key, value) {
  const next = { ...local, [key]: value }
  if (!value || value === 'all') delete next[key]
  emit('update:modelValue', next)
  emit('change', next)
}

function setUnconfigured() {
  const next = { ...local, status: 'unassigned' }
  delete next.search
  emit('update:modelValue', next)
  emit('change', next)
}
</script>
