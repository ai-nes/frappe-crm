<template>
  <section class="assignment-overview-table overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white shadow-sm" data-testid="assignment-overview-table">
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-outline-gray-1 px-4 py-3">
      <div>
        <h2 class="font-semibold text-ink-gray-9">{{ __('2. Cây phân bổ hiện tại') }}</h2>
        <p class="mt-0.5 text-xs text-ink-gray-5">{{ __('Cụm → Địa bàn → Trường → Nhóm → Nhân sự') }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs text-ink-gray-5">{{ visibleRows.length }}/{{ rows.length }} {{ __('dòng đang xem') }}</span>
        <Button size="sm" variant="subtle" :label="__('Mở tới địa bàn')" iconLeft="chevrons-down" @click="expandToLocations" />
        <Button size="sm" variant="subtle" :label="__('Thu gọn')" iconLeft="chevrons-up" @click="collapseAll" />
      </div>
    </div>
    <div v-if="loading && !rows.length" class="flex min-h-56 items-center justify-center" role="status">
      <LoadingIndicator class="size-6" />
      <span class="sr-only">{{ __('Đang tải cây phân bổ') }}</span>
    </div>
    <div v-else-if="!rows.length" class="p-10 text-center text-sm text-ink-gray-5">
      {{ __('Không có dữ liệu phù hợp với bộ lọc.') }}
    </div>
    <div v-else class="overflow-x-auto">
      <table class="w-full min-w-[1320px] table-fixed text-sm">
        <colgroup>
          <col v-if="selectable" class="w-12" />
          <col class="w-[30%]" />
          <col class="w-[16%]" />
          <col class="w-[23%]" />
          <col class="w-[19%]" />
          <col class="w-[8%]" />
          <col class="w-[110px]" />
        </colgroup>
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
            <th class="px-4 py-3">{{ __('Cây phân bổ') }}</th>
            <th class="px-4 py-3">{{ __('Phạm vi') }}</th>
            <th class="px-4 py-3">{{ __('Phụ trách') }}</th>
            <th class="px-4 py-3">{{ __('Điều phối') }}</th>
            <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Thao tác') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in visibleRows"
            :key="row.id"
            class="cursor-pointer border-t border-outline-gray-1 align-top hover:bg-surface-gray-2/60 focus-within:bg-surface-gray-2/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-400"
            tabindex="0"
            :aria-label="`${levelLabel(row.level)}: ${row.label}`"
            @click="select(row)"
            @keydown.enter.self.prevent="select(row)"
            @keydown.space.self.prevent="select(row)"
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
            <td class="px-4 py-3" :class="rowTone(row)">
              <div class="flex items-start gap-1.5" :style="{ paddingLeft: `${indent(row)}px` }">
                <button
                  v-if="row.has_children"
                  type="button"
                  data-testid="expand-assignment-node"
                  :data-level="row.level"
                  class="mt-0.5 inline-flex min-h-11 min-w-11 items-center justify-center rounded text-ink-gray-5 hover:bg-surface-gray-3 hover:text-ink-gray-8 focus:outline-none focus:ring-2 focus:ring-outline-gray-4"
                  :aria-label="expanded.has(row.id) ? __('Thu gọn') : __('Mở rộng')"
                  :aria-expanded="expanded.has(row.id)"
                  @click.stop="toggle(row.id)"
                >
                  <FeatherIcon :name="expanded.has(row.id) ? 'chevron-down' : 'chevron-right'" class="size-4" aria-hidden="true" />
                </button>
                <span v-else class="inline-block w-5" aria-hidden="true" />
                <div>
                  <p class="font-medium text-ink-gray-9">{{ row.label }}</p>
                  <p class="mt-0.5 text-[11px] uppercase tracking-wide text-ink-gray-5">{{ levelLabel(row.level) }}<span v-if="row.zone_code" class="ml-1 normal-case tracking-normal text-ink-gray-4">· {{ row.zone_code }}</span></p>
                </div>
              </div>
            </td>
            <td class="px-4 py-3 align-top">
              <p class="font-medium text-ink-gray-8">{{ scopeTitle(row) }}</p>
              <p class="mt-0.5 text-xs text-ink-gray-5">{{ scopeMeta(row) }}</p>
            </td>
            <td class="px-4 py-3 align-top">
              <p class="font-medium text-ink-gray-8">{{ ownerTitle(row) }}</p>
              <p v-if="ownerMeta(row)" class="mt-0.5 max-w-[360px] break-words text-xs leading-5 text-ink-gray-5" :title="ownerMeta(row)">{{ ownerMeta(row) }}</p>
            </td>
            <td class="px-4 py-3 align-top">
              <p class="max-w-[300px] break-words font-medium leading-5 text-ink-gray-8">{{ routingTitle(row) }}</p>
              <p class="mt-0.5 break-words text-xs leading-5 text-ink-gray-5">{{ routingMeta(row) }}</p>
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
  cluster: 'Cụm tuyển sinh',
  zone: 'Địa bàn',
  high_school: 'Trường THPT',
  team: 'Nhóm phụ trách',
  staff: 'Nhân sự',
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
    const available = new Set(rows.map((row) => row.id))
    const next = new Set([...expanded.value].filter((id) => available.has(id)))
    if (!next.size) {
      for (const row of rows) {
        if (['campus', 'province', 'cluster'].includes(row.level)) next.add(row.id)
      }
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

function formatNumber(value) {
  return new Intl.NumberFormat('vi-VN').format(Number(value || 0))
}

function scopeTitle(row) {
  if (row.level === 'province') return `${formatNumber(row.cluster_count)} ${__('cụm')}`
  if (row.level === 'cluster') return `${formatNumber(row.zone_count)} ${__('địa bàn')}`
  if (row.level === 'zone') return `${formatNumber(row.ward_count)} ${__('phường/xã')}`
  if (row.level === 'high_school') return row.ward_name || __('Chưa có phường/xã')
  if (row.level === 'team') return `${formatNumber(row.member_count)} ${__('nhân sự')}`
  if (row.level === 'staff') return row.function || __('Nhân sự vận hành')
  return row.province_name || __('Toàn bộ phạm vi')
}

function scopeMeta(row) {
  if (['province', 'cluster'].includes(row.level)) return `${formatNumber(row.zone_count)} ${__('địa bàn')} · ${formatNumber(row.school_count)} ${__('trường')}`
  if (row.level === 'zone') return `${formatNumber(row.school_count)} ${__('trường')} · ${formatNumber(row.active_students)} ${__('Lead hoạt động')}`
  if (row.level === 'team') return `${formatNumber(row.zone_count)} ${__('địa bàn')} · ${formatNumber(row.school_count)} ${__('trường')}`
  if (row.level === 'staff') return `${formatNumber(row.active_students)} ${__('Lead đang giữ')}`
  if (row.level === 'high_school') return row.active_students ? `${formatNumber(row.active_students)} ${__('Lead hoạt động')}` : __('Chưa có Lead hoạt động')
  return `${formatNumber(row.active_students)} ${__('Lead hoạt động')}`
}

function ownerTitle(row) {
  if (row.level === 'zone') return row.team_name || __('Chưa có Team')
  if (row.level === 'team') return `${formatNumber(row.member_count)} ${__('thành viên Team')}`
  if (row.level === 'staff') return row.team_name || __('Chưa thuộc Team')
  if (row.level === 'high_school') {
    if (row.staff_names?.length) return row.staff_names.join(', ')
    if (row.team_names?.length) return row.team_names.join(', ')
    return __('Theo Team của địa bàn')
  }
  if (row.team_names?.length) return row.team_names.join(', ')
  return __('Theo cấp bên dưới')
}

function ownerMeta(row) {
  if (['team', 'zone'].includes(row.level)) return memberSummary(row.member_names)
  if (row.level === 'high_school') {
    const ward = row.ward_name ? `${__('Phường/xã')}: ${row.ward_name}` : ''
    if (row.inherited_from_zone) {
      return [ward, __('Kế thừa từ địa bàn'), row.has_stale_school_override ? __('Có mapping trường cần rà soát') : '']
        .filter(Boolean)
        .join(' · ')
    }
    return ward
  }
  return ''
}

function memberSummary(names = []) {
  if (!names.length) return ''
  if (names.length <= 3) return names.join(', ')
  return `${names.slice(0, 2).join(', ')} · +${names.length - 2} ${__('người')}`
}

function routingTitle(row) {
  if (row.pool_names?.length) return row.pool_names.join(', ')
  if (row.level === 'staff' && row.load_percent !== null && row.load_percent !== undefined) return `${row.load_percent}% ${__('tải hiện tại')}`
  return row.level === 'high_school' ? __('Theo Pool của Team') : '—'
}

function routingMeta(row) {
  if (row.level === 'staff') return row.capacity ? `${row.active_students || 0}/${row.capacity} ${__('Lead đang giữ')}` : __('Chưa đặt capacity')
  return row.active_students ? `${formatNumber(row.active_students)} ${__('Lead hoạt động')}` : __('Chưa có Lead hoạt động')
}

function rowTone(row) {
  return {
    'bg-blue-50/30': row.level === 'zone',
    'bg-surface-gray-1/40': row.level === 'team',
  }
}

function toggle(id) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function expandToLocations() {
  expanded.value = new Set(props.rows.filter((row) => ['campus', 'province', 'cluster'].includes(row.level)).map((row) => row.id))
}

function collapseAll() {
  expanded.value = new Set()
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
