<template>
  <div
    class="flex items-center gap-2 rounded-md border-l-2 px-2 py-2 hover:bg-surface-gray-2"
    :class="active ? 'border-l-orange-500 bg-orange-50' : 'border-l-transparent'"
  >
    <slot name="prefix" />
    <div
      class="flex min-w-0 flex-1 cursor-pointer items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-400"
      role="button"
      tabindex="0"
      :aria-pressed="active"
      :aria-label="`${levelLabel}: ${row.label}`"
      @click="$emit('select')"
      @keydown.enter.prevent="$emit('select')"
      @keydown.space.prevent="$emit('select')"
    >
      <span class="flex size-6 shrink-0 items-center justify-center rounded" :class="levelDotClass">
        <FeatherIcon :name="levelIcon" class="size-3.5" />
      </span>
      <span class="min-w-0 flex-1 truncate text-xs font-medium text-ink-gray-9">{{ row.label }}</span>
      <span class="shrink-0 text-[11px] text-ink-gray-5">{{ metaText }}</span>
      <span class="size-2 shrink-0 rounded-full" :class="statusDotClass" />
    </div>
    <button
      v-if="hasChildren"
      type="button"
      class="flex shrink-0 items-center justify-center text-ink-gray-4"
      data-testid="expand-assignment-node"
      :data-level="row.level"
      :aria-label="__('Mở rộng')"
      @click="$emit('select')"
    >
      <FeatherIcon name="chevron-right" class="size-3.5" />
    </button>
    <span v-else class="size-3.5 shrink-0" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { FeatherIcon } from 'frappe-ui'
import { assignmentWorkspaceStatusTone } from '@/data/assignmentWorkspace'

const props = defineProps({
  row: { type: Object, required: true },
  active: Boolean,
  hasChildren: Boolean,
  metaText: { type: String, default: '' },
})
defineEmits(['select'])

const levelLabels = {
  campus: 'Campus',
  province: 'Tỉnh/TP',
  cluster: 'Cụm tuyển sinh',
  zone: 'Địa bàn',
  high_school: 'Trường THPT',
  team: 'Nhóm phụ trách',
  staff: 'Nhân sự',
}
const levelIcons = {
  campus: 'server',
  province: 'map',
  cluster: 'layers',
  zone: 'map-pin',
  high_school: 'book-open',
  team: 'users',
  staff: 'user',
}
const levelDotClasses = {
  campus: 'bg-violet-50 text-violet-600',
  province: 'bg-blue-50 text-blue-600',
  cluster: 'bg-blue-50 text-blue-600',
  zone: 'bg-cyan-50 text-cyan-700',
  high_school: 'bg-surface-gray-3 text-ink-gray-7',
  team: 'bg-green-50 text-green-700',
  staff: 'bg-amber-50 text-amber-700',
}
const toneDotClasses = {
  success: 'bg-green-500',
  warning: 'bg-orange-400',
  caution: 'bg-yellow-500',
  neutral: 'bg-gray-300',
}

const levelLabel = computed(() => levelLabels[props.row.level] || props.row.level)
const levelIcon = computed(() => levelIcons[props.row.level] || 'circle')
const levelDotClass = computed(() => levelDotClasses[props.row.level] || 'bg-surface-gray-3 text-ink-gray-7')
const statusDotClass = computed(() => toneDotClasses[assignmentWorkspaceStatusTone(props.row.status)])
</script>
