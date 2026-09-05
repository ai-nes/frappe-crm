<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-white shadow-sm" data-testid="assignment-overview-filters">
    <div class="flex min-h-14 flex-wrap items-center justify-between gap-2 px-4 py-2.5">
      <div class="flex min-w-0 flex-wrap items-center gap-2">
        <FeatherIcon name="filter" class="size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
        <h2 class="text-sm font-medium text-ink-gray-8">{{ __('Bộ lọc') }}</h2>
        <span class="text-xs text-ink-gray-5">{{ __('Cây phân bổ') }}</span>
        <span v-if="activeFilterCount" class="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
          {{ activeFilterCount }} {{ __('đang dùng') }}
        </span>
        <span v-else class="text-xs text-ink-gray-5">{{ __('Không lọc') }}</span>
      </div>
      <div class="flex flex-wrap items-center justify-end gap-1.5">
        <Button
          v-if="activeFilterCount"
          variant="ghost"
          size="sm"
          :label="__('Xoá')"
          iconLeft="x"
          @click="$emit('reset')"
        />
        <Button
          variant="subtle"
          size="sm"
          :label="showFilters ? __('Thu gọn') : __('Mở bộ lọc')"
          :iconLeft="showFilters ? 'chevron-up' : 'filter'"
          :aria-expanded="showFilters"
          aria-controls="assignment-filter-controls"
          @click="showFilters = !showFilters"
        />
      </div>
    </div>
    <div v-if="showFilters" id="assignment-filter-controls" class="border-t border-outline-gray-1 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.35fr_1fr_1fr]">
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
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          class="inline-flex min-h-10 items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-orange-300"
          :class="local.status === 'unassigned' ? 'border-orange-300 bg-orange-100 text-orange-900' : 'border-orange-200 bg-orange-50 text-orange-800 hover:bg-orange-100'"
          :aria-pressed="local.status === 'unassigned'"
          @click="toggleUnconfigured"
        >
          <FeatherIcon name="alert-circle" class="size-4" aria-hidden="true" />
          {{ local.status === 'unassigned' ? __('Đang xem chưa cấu hình') : __('Chỉ xem chưa cấu hình') }}
        </button>
        <button
          type="button"
          class="inline-flex min-h-10 items-center gap-1.5 rounded-md border border-outline-gray-2 px-3 py-2 text-sm font-medium text-ink-gray-7 hover:bg-surface-gray-2 focus:outline-none focus:ring-2 focus:ring-outline-gray-4"
          :aria-expanded="showAdvanced"
          aria-controls="assignment-advanced-filters"
          @click="showAdvanced = !showAdvanced"
        >
          <FeatherIcon :name="showAdvanced ? 'chevron-up' : 'chevron-down'" class="size-4" aria-hidden="true" />
          {{ showAdvanced ? __('Ẩn bộ lọc địa bàn & phụ trách') : __('Thêm bộ lọc địa bàn & phụ trách') }}
        </button>
      </div>
      <div v-if="showAdvanced" id="assignment-advanced-filters" class="mt-3 grid gap-3 rounded-md border border-outline-gray-1 bg-surface-gray-1 p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
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
const showFilters = ref(false)
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
