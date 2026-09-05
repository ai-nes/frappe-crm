<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 shadow-sm">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div>
        <div class="flex items-center gap-2">
          <h2 class="font-semibold text-ink-gray-9">{{ __('Bộ lọc phân bổ') }}</h2>
          <span v-if="activeFilterCount" class="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
            {{ activeFilterCount }} {{ __('đang dùng') }}
          </span>
        </div>
        <p class="mt-0.5 text-xs text-ink-gray-5">{{ __('Tìm nhanh theo trạng thái hoặc mở thêm bộ lọc địa bàn.') }}</p>
      </div>
      <Button
        variant="subtle"
        size="sm"
        :label="__('Xoá bộ lọc')"
        iconLeft="x"
        @click="$emit('reset')"
      />
    </div>
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <FormControl
        v-model="local.search"
        :label="__('Tìm kiếm')"
        :placeholder="__('Tên trường, nhóm, nhân sự...')"
        @update:modelValue="change('search', $event)"
      />
      <FormControl
        v-for="field in primaryFields"
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
      class="mt-3 inline-flex min-h-11 items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-orange-300"
      :class="local.status === 'unassigned' ? 'border-orange-300 bg-orange-100 text-orange-900' : 'border-orange-200 bg-orange-50 text-orange-800 hover:bg-orange-100'"
      :aria-pressed="local.status === 'unassigned'"
      @click="toggleUnconfigured"
    >
      <FeatherIcon name="alert-circle" class="size-4" aria-hidden="true" />
      {{ local.status === 'unassigned' ? __('Đang xem phần chưa cấu hình') : __('Chỉ xem phần chưa cấu hình') }}
    </button>
    <button
      type="button"
      class="ml-2 inline-flex min-h-11 items-center gap-1.5 rounded-md border border-outline-gray-2 px-3 py-2 text-sm font-medium text-ink-gray-7 hover:bg-surface-gray-2 focus:outline-none focus:ring-2 focus:ring-outline-gray-4"
      :aria-expanded="showAdvanced"
      aria-controls="assignment-advanced-filters"
      @click="showAdvanced = !showAdvanced"
    >
      <FeatherIcon :name="showAdvanced ? 'chevron-up' : 'chevron-down'" class="size-4" aria-hidden="true" />
      {{ showAdvanced ? __('Ẩn bộ lọc nâng cao') : __('Bộ lọc địa bàn & phụ trách') }}
    </button>
    <div v-if="showAdvanced" id="assignment-advanced-filters" class="mt-3 grid gap-3 border-t border-outline-gray-1 pt-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      <FormControl
        v-for="field in advancedFields"
        :key="field.key"
        v-model="local[field.key]"
        type="select"
        :label="__(field.label)"
        :options="field.options"
        @update:modelValue="change(field.key, $event)"
      />
    </div>
  </section>
</template>

<script setup>
import { Button, FeatherIcon, FormControl } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
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
const showAdvanced = ref(false)

watch(
  () => props.modelValue,
  (value) => {
    const next = value || {}
    Object.keys(local).forEach((key) => {
      if (!(key in next)) delete local[key]
    })
    Object.assign(local, next)
    showAdvanced.value = hasAdvancedFilters(next)
  },
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

const primaryFields = computed(() => selectFields.value.filter((field) => ['status', 'workload'].includes(field.key)))
const advancedFields = computed(() => selectFields.value.filter((field) => !['status', 'workload'].includes(field.key)))
const activeFilterCount = computed(
  () => Object.entries(local).filter(([, value]) => value !== undefined && value !== null && value !== '' && value !== 'all').length,
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

function toggleUnconfigured() {
  if (local.status === 'unassigned') {
    const next = { ...local }
    delete next.status
    emit('update:modelValue', next)
    emit('change', next)
    return
  }
  setUnconfigured()
}

function hasAdvancedFilters(value = {}) {
  return Object.entries(value).some(
    ([key, entry]) => !['search', 'status', 'workload'].includes(key) && entry !== undefined && entry !== null && entry !== '' && entry !== 'all',
  )
}
</script>
