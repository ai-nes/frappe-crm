<template>
  <section class="assignment-overview-table overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white shadow-sm" data-testid="assignment-overview-table">
    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-outline-gray-1 px-4 py-3">
      <div>
        <h2 class="font-semibold text-ink-gray-9">{{ __('2. Cây phân bổ hiện tại') }}</h2>
        <p class="mt-0.5 text-xs text-ink-gray-5">{{ __('Campus → Tỉnh/TP → Cluster → Zone → Trường THPT → Team → Staff') }}</p>
      </div>
      <span class="text-xs text-ink-gray-5">{{ rows.length }} {{ __('dòng') }}</span>
    </div>
    <div v-if="loading && !rows.length" class="flex min-h-56 items-center justify-center" role="status">
      <LoadingIndicator class="size-6" />
      <span class="sr-only">{{ __('Đang tải cây phân bổ') }}</span>
    </div>
    <div v-else-if="!rows.length" class="p-10 text-center text-sm text-ink-gray-5">
      {{ __('Không có dữ liệu phù hợp với bộ lọc.') }}
    </div>
    <div v-else class="overflow-x-auto">
      <table class="w-full min-w-[1220px] text-sm">
        <thead class="bg-surface-gray-2 text-left text-xs text-ink-gray-6">
          <tr>
            <th v-if="selectable" class="w-10 px-3 py-3">
              <input
                type="checkbox"
                :checked="allVisibleSchoolsSelected"
                :indeterminate="someVisibleSchoolsSelected && !allVisibleSchoolsSelected"
                :aria-label="__('Chọn tất cả trường đang hiển thị')"
                @click.stop="toggleAllVisibleSchools"
              />
            </th>
            <th class="w-[25%] px-4 py-3">{{ __('Cây cấu hình') }}</th>
            <th class="px-4 py-3">{{ __('Tỉnh/TP') }}</th>
            <th class="px-4 py-3">{{ __('Zone') }}</th>
            <th class="px-4 py-3">{{ __('Nhóm') }}</th>
            <th class="px-4 py-3">{{ __('Nhân viên phụ trách') }}</th>
            <th class="px-4 py-3">{{ __('Pool') }}</th>
            <th class="px-4 py-3">{{ __('Tải') }}</th>
            <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Thao tác') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in visibleRows"
            :key="row.id"
            class="cursor-pointer border-t border-outline-gray-1 align-top hover:bg-surface-gray-2/60 focus-within:bg-surface-gray-2/60"
            @click="select(row)"
          >
            <td v-if="selectable" class="px-3 py-3" @click.stop>
              <input
                v-if="row.level === 'high_school'"
                type="checkbox"
                :checked="selectedSchoolIds.includes(row.high_school_id)"
                :aria-label="__('Chọn trường {0}', [row.label])"
                :data-testid="`select-school-${row.high_school_id}`"
                @change="toggleSchool(row.high_school_id)"
              />
            </td>
            <td class="px-4 py-3">
              <div class="flex items-start gap-1.5" :style="{ paddingLeft: `${indent(row)}px` }">
                <button
                  v-if="row.has_children"
                  type="button"
                  class="mt-0.5 rounded p-0.5 text-ink-gray-5 hover:bg-surface-gray-3 hover:text-ink-gray-8 focus:outline-none focus:ring-2 focus:ring-outline-gray-4"
                  :aria-label="expanded.has(row.id) ? __('Thu gọn') : __('Mở rộng')"
                  @click.stop="toggle(row.id)"
                >
                  <FeatherIcon :name="expanded.has(row.id) ? 'chevron-down' : 'chevron-right'" class="size-4" aria-hidden="true" />
                </button>
                <span v-else class="inline-block w-5" aria-hidden="true" />
                <div>
                  <p class="font-medium text-ink-gray-9">{{ row.label }}</p>
                  <p class="mt-0.5 text-[11px] uppercase tracking-wide text-ink-gray-5">{{ levelLabel(row.level) }}</p>
                </div>
              </div>
            </td>
            <td class="px-4 py-3 text-ink-gray-7">{{ row.province_name || row.province_id || '—' }}</td>
            <td class="px-4 py-3 text-ink-gray-7">{{ row.zone_name || row.zone_id || '—' }}</td>
            <td class="px-4 py-3">
              <span v-if="row.team_names?.length">{{ row.team_names.join(', ') }}</span>
              <span v-else>{{ row.team_name || '—' }}</span>
            </td>
            <td class="px-4 py-3">
              <span v-if="row.staff_names?.length">{{ row.staff_names.join(', ') }}</span>
              <span v-else>{{ row.label && row.level === 'staff' ? row.label : '—' }}</span>
            </td>
            <td class="px-4 py-3 text-ink-gray-7">
              <span v-if="row.pool_names?.length">{{ row.pool_names.join(', ') }}</span>
              <span v-else>—</span>
            </td>
            <td class="px-4 py-3 whitespace-nowrap">
              <p>{{ row.active_students ?? 0 }} {{ __('hồ sơ') }}</p>
              <p v-if="row.load_percent !== null && row.load_percent !== undefined" class="mt-0.5 text-xs text-ink-gray-5">{{ row.load_percent }}%</p>
            </td>
            <td class="px-4 py-3"><StatusChip :status="row.status" /></td>
            <td class="px-4 py-3 text-right">
              <button type="button" class="text-xs font-medium text-blue-600 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400" @click.stop="select(row)">
                {{ __('Xem chi tiết') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="nextCursor" class="flex justify-center border-t border-outline-gray-1 p-3">
      <Button :label="__('Tải thêm')" :loading="loading" @click="loadMore" />
    </div>
  </section>
</template>

<script setup>
import { Button, FeatherIcon, LoadingIndicator } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import StatusChip from './StatusChip.vue'
import { assignmentWorkspaceLevels } from '@/data/assignmentWorkspace'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  loading: Boolean,
  nextCursor: { type: [String, Number], default: null },
  selectable: Boolean,
  selectedSchoolIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['select', 'load-more', 'toggle-school', 'toggle-all-schools'])
const expanded = ref(new Set())
const levelLabels = {
  campus: 'Campus',
  province: 'Tỉnh/TP',
  cluster: 'Cluster',
  zone: 'Zone',
  high_school: 'Trường THPT',
  team: 'Team',
  staff: 'Staff',
}

const rowMap = computed(() => new Map(props.rows.map((row) => [row.id, row])))

const visibleRows = computed(() =>
  props.rows.filter((row) => {
    let parent = row.parent_id
    while (parent) {
      if (!expanded.value.has(parent)) return false
      parent = rowMap.value.get(parent)?.parent_id
    }
    return true
  }),
)

const visibleSchools = computed(() =>
  visibleRows.value.filter((row) => row.level === 'high_school' && row.high_school_id),
)
const allVisibleSchoolsSelected = computed(
  () => Boolean(visibleSchools.value.length) && visibleSchools.value.every((row) => props.selectedSchoolIds.includes(row.high_school_id)),
)
const someVisibleSchoolsSelected = computed(
  () => visibleSchools.value.some((row) => props.selectedSchoolIds.includes(row.high_school_id)),
)

watch(
  () => props.rows,
  (rows) => {
    const next = new Set(expanded.value)
    for (const row of rows) {
      if (row.has_children) next.add(row.id)
    }
    expanded.value = next
  },
  { immediate: true },
)

function indent(row) {
  return Math.max(0, assignmentWorkspaceLevels.indexOf(row.level)) * 18
}

function levelLabel(level) {
  return levelLabels[level] || level
}

function toggle(id) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function select(row) {
  emit('select', row)
}

function loadMore() {
  emit('load-more')
}

function toggleSchool(highSchoolId) {
  emit('toggle-school', highSchoolId)
}

function toggleAllVisibleSchools() {
  emit('toggle-all-schools', visibleSchools.value.map((row) => row.high_school_id))
}
</script>
