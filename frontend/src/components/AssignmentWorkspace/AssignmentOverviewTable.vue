<template>
  <section class="assignment-overview-table overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white shadow-sm" data-testid="assignment-overview-table">
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-outline-gray-1 px-4 py-3">
      <h2 class="font-semibold text-ink-gray-9">{{ __('2. Cây phân bổ hiện tại') }}</h2>
      <div class="flex flex-wrap items-center gap-2">
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

    <template v-else>
      <div class="flex flex-wrap items-center gap-1 border-b border-outline-gray-1 bg-surface-gray-1 px-4 py-2.5">
        <template v-for="(crumb, index) in breadcrumbChain" :key="crumb.id">
          <FeatherIcon v-if="index > 0" name="chevron-right" class="size-3 shrink-0 text-ink-gray-4" aria-hidden="true" />
          <button
            v-if="isCrumbNavigable(crumb)"
            type="button"
            class="rounded px-1.5 py-0.5 text-xs font-medium text-ink-gray-6 hover:bg-surface-gray-3 hover:text-ink-gray-9 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
            :class="index === breadcrumbChain.length - 1 ? 'text-ink-gray-9' : ''"
            @click="goToCrumb(crumb)"
          >
            {{ crumb.label }}
          </button>
          <span v-else class="px-1.5 py-0.5 text-xs font-medium text-ink-gray-5">{{ crumb.label }}</span>
        </template>
      </div>

      <div class="grid grid-cols-1 divide-y divide-outline-gray-1 lg:grid-cols-[1fr_1fr_1.15fr_1.3fr] lg:divide-x lg:divide-y-0">
        <!-- Column 1: clusters -->
        <div class="max-h-[520px] overflow-y-auto p-2">
          <p class="sticky top-0 flex items-center justify-between bg-surface-white px-2 py-2 text-[10px] font-semibold uppercase tracking-wide text-ink-gray-4">
            {{ __('Cụm tuyển sinh') }}<span class="font-medium normal-case text-ink-gray-5">{{ clusters.length }}</span>
          </p>
          <ColumnItem
            v-for="row in clusters"
            :key="row.id"
            :row="row"
            :active="row.id === selectedClusterId"
            :has-children="Boolean(row.children?.length)"
            :meta-text="scopeTitle(row)"
            @select="selectCluster(row)"
          />
        </div>

        <!-- Column 2: zones -->
        <div class="max-h-[520px] overflow-y-auto p-2">
          <p class="sticky top-0 flex items-center justify-between bg-surface-white px-2 py-2 text-[10px] font-semibold uppercase tracking-wide text-ink-gray-4">
            {{ __('Địa bàn') }}<span class="font-medium normal-case text-ink-gray-5">{{ zones.length }}</span>
          </p>
          <p v-if="!zones.length" class="px-2 py-6 text-center text-xs text-ink-gray-4">{{ __('Chọn một cụm để xem địa bàn.') }}</p>
          <ColumnItem
            v-for="row in zones"
            :key="row.id"
            :row="row"
            :active="row.id === selectedZoneId"
            :has-children="Boolean(row.children?.length)"
            :meta-text="scopeTitle(row)"
            @select="selectZone(row)"
          />
        </div>

        <!-- Column 3: facet (schools / team & staff) -->
        <div class="max-h-[520px] overflow-y-auto p-2">
          <p class="sticky top-0 flex items-center justify-between bg-surface-white px-2 py-2 text-[10px] font-semibold uppercase tracking-wide text-ink-gray-4">
            {{ __('Phạm vi & Nhân lực') }}<span class="font-medium normal-case text-ink-gray-5">{{ schools.length + teams.length }}</span>
          </p>
          <p v-if="!selectedZoneId" class="px-2 py-6 text-center text-xs text-ink-gray-4">{{ __('Chọn một địa bàn để xem trường và nhóm.') }}</p>
          <template v-else-if="!schools.length && !teams.length">
            <p class="px-2 py-6 text-center text-xs text-ink-gray-4">{{ __('Địa bàn này chưa gán trường hay nhóm nào.') }}</p>
          </template>
          <template v-else>
            <div class="mb-2 flex gap-1 px-1">
              <button
                type="button"
                class="flex-1 rounded-md border px-2 py-1.5 text-xs font-medium"
                :class="facet === 'school' ? 'border-orange-500 bg-orange-50 text-ink-gray-9' : 'border-transparent bg-surface-gray-1 text-ink-gray-5'"
                @click="selectFacet('school')"
              >
                {{ __('Trường phụ trách') }} ({{ schools.length }})
              </button>
              <button
                type="button"
                class="flex-1 rounded-md border px-2 py-1.5 text-xs font-medium"
                :class="facet === 'team' ? 'border-orange-500 bg-orange-50 text-ink-gray-9' : 'border-transparent bg-surface-gray-1 text-ink-gray-5'"
                @click="selectFacet('team')"
              >
                {{ __('Đội & nhân sự') }} ({{ teams.length }})
              </button>
            </div>
            <div v-if="facet === 'school'">
              <p v-if="!schools.length" class="px-2 py-6 text-center text-xs text-ink-gray-4">{{ __('Chưa có trường nào được gán cho địa bàn này.') }}</p>
              <div v-else-if="selectable" class="flex items-center gap-2 px-2 pb-1.5 text-xs text-ink-gray-5">
                <input
                  type="checkbox"
                  :checked="allVisibleSchoolsSelected"
                  :indeterminate="someVisibleSchoolsSelected && !allVisibleSchoolsSelected"
                  :aria-label="__('Chọn tất cả trường đang hiển thị')"
                  @click.stop="toggleAllVisibleSchools"
                />
                {{ __('Chọn tất cả') }}
              </div>
              <ColumnItem
                v-for="row in schools"
                :key="row.id"
                :row="row"
                :active="row.id === selectedLeafId"
                :meta-text="row.active_students ? `${formatNumber(row.active_students)} Lead` : __('Chưa có Lead')"
                @select="selectLeaf(row)"
              >
                <template v-if="selectable" #prefix>
                  <input
                    type="checkbox"
                    :checked="selectedSchoolIds.includes(row.high_school_id)"
                    :aria-label="__('Chọn trường {0}', [row.label])"
                    :data-testid="`select-school-${row.high_school_id}`"
                    @click.stop="toggleSchool(row.high_school_id)"
                  />
                </template>
              </ColumnItem>
            </div>
            <div v-else>
              <p v-if="!teams.length" class="px-2 py-6 text-center text-xs text-ink-gray-4">{{ __('Địa bàn này chưa có nhóm phụ trách nào.') }}</p>
              <ColumnItem
                v-for="row in teams"
                :key="row.id"
                :row="row"
                :active="row.id === selectedLeafId"
                :has-children="Boolean(row.children?.length)"
                :meta-text="`${formatNumber(row.member_count)} ${__('thành viên')}`"
                @select="selectLeaf(row)"
              />
            </div>
          </template>
        </div>

        <!-- Column 4: detail -->
        <div class="max-h-[520px] overflow-y-auto p-4">
          <div v-if="!detailNode" class="flex flex-col items-center gap-2 py-10 text-center text-xs text-ink-gray-4">
            <FeatherIcon name="mouse-pointer-click" class="size-5" aria-hidden="true" />
            {{ __('Chọn một dòng bên trái để xem chi tiết.') }}
          </div>
          <template v-else>
            <div class="flex items-start gap-2.5">
              <span class="flex size-8 shrink-0 items-center justify-center rounded-lg" :class="levelDotClass(detailNode.level)">
                <FeatherIcon :name="levelIcon(detailNode.level)" class="size-4" aria-hidden="true" />
              </span>
              <div class="min-w-0">
                <p class="text-[10px] font-semibold uppercase tracking-wide text-ink-gray-4">{{ levelLabel(detailNode.level) }}</p>
                <p class="break-words font-semibold text-ink-gray-9">{{ detailNode.label }}</p>
                <StatusChip class="mt-1" :status="detailNode.status" />
              </div>
            </div>

            <div class="mt-4 border-t border-outline-gray-1 pt-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-ink-gray-4">{{ __('Phạm vi') }}</p>
              <p class="mt-1.5 font-medium text-ink-gray-8">{{ scopeTitle(detailNode) }}</p>
              <p class="mt-0.5 text-xs text-ink-gray-5">{{ scopeMeta(detailNode) }}</p>
            </div>

            <div class="mt-3 border-t border-outline-gray-1 pt-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-ink-gray-4">{{ __('Phụ trách') }}</p>
              <p class="mt-1.5 font-medium text-ink-gray-8">{{ ownerTitle(detailNode) }}</p>
              <p v-if="ownerMeta(detailNode)" class="mt-0.5 break-words text-xs leading-5 text-ink-gray-5">{{ ownerMeta(detailNode) }}</p>
            </div>

            <div class="mt-3 border-t border-outline-gray-1 pt-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-ink-gray-4">{{ __('Điều phối') }}</p>
              <p class="mt-1.5 break-words font-medium leading-5 text-ink-gray-8">{{ routingTitle(detailNode) }}</p>
              <p class="mt-0.5 break-words text-xs leading-5 text-ink-gray-5">{{ routingMeta(detailNode) }}</p>
            </div>

            <div v-if="detailNode.level === 'team' && staffOfDetail.length" class="mt-3 border-t border-outline-gray-1 pt-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-ink-gray-4">{{ __('Nhân sự trong đội') }} ({{ staffOfDetail.length }})</p>
              <div v-for="staff in staffOfDetail" :key="staff.id" class="mt-2 flex items-center gap-2">
                <span class="flex size-5 shrink-0 items-center justify-center rounded" :class="levelDotClass('staff')">
                  <FeatherIcon name="user" class="size-3" aria-hidden="true" />
                </span>
                <span class="flex-1 truncate text-xs font-medium text-ink-gray-8">{{ staff.label }}</span>
                <span v-if="staff.load_percent !== null && staff.load_percent !== undefined" class="w-14 shrink-0">
                  <span class="block h-1.5 overflow-hidden rounded-full bg-surface-gray-2">
                    <span class="block h-full rounded-full" :class="staff.load_percent >= 70 ? 'bg-orange-400' : 'bg-blue-500'" :style="{ width: `${staff.load_percent}%` }" />
                  </span>
                </span>
              </div>
            </div>

            <button
              type="button"
              class="mt-4 w-full rounded-md border border-outline-gray-3 bg-surface-white py-2 text-xs font-medium text-ink-gray-8 hover:bg-surface-gray-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
              @click="select(detailNode)"
            >
              {{ __('Xem chi tiết đầy đủ') }}
            </button>
          </template>
        </div>
      </div>
    </template>

    <div v-if="nextCursor" class="flex justify-center border-t border-outline-gray-1 p-3">
      <Button :label="__('Tải thêm')" :loading="loading" @click="loadMore" />
    </div>
  </section>
</template>

<script setup>
import { Button, FeatherIcon, LoadingIndicator } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import StatusChip from './StatusChip.vue'
import ColumnItem from './AssignmentColumnItem.vue'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  loading: Boolean,
  nextCursor: { type: [String, Number], default: null },
  selectable: Boolean,
  selectedSchoolIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['select', 'load-more', 'toggle-school', 'toggle-all-schools'])

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

function levelLabel(level) {
  return levelLabels[level] || level
}
function levelIcon(level) {
  return levelIcons[level] || 'circle'
}
function levelDotClass(level) {
  return levelDotClasses[level] || 'bg-surface-gray-3 text-ink-gray-7'
}

const rowMap = computed(() => new Map(props.rows.map((row) => [row.id, row])))

function childrenRows(parentId) {
  if (!parentId) return []
  const parent = rowMap.value.get(parentId)
  return (parent?.children || []).map((id) => rowMap.value.get(id)).filter(Boolean)
}

const clusters = computed(() => props.rows.filter((row) => row.level === 'cluster'))
const selectedClusterId = ref(null)
const selectedZoneId = ref(null)
const selectedLeafId = ref(null)
const facet = ref('school')

const zones = computed(() => childrenRows(selectedClusterId.value))
const zoneLeafChildren = computed(() => childrenRows(selectedZoneId.value))
const schools = computed(() => zoneLeafChildren.value.filter((row) => row.level === 'high_school'))
const teams = computed(() => zoneLeafChildren.value.filter((row) => row.level === 'team'))
const detailNode = computed(() => rowMap.value.get(selectedLeafId.value) || rowMap.value.get(selectedZoneId.value) || null)
const staffOfDetail = computed(() => (detailNode.value ? childrenRows(detailNode.value.id).filter((row) => row.level === 'staff') : []))

function pickDefaults() {
  const clusterList = clusters.value
  if (!clusterList.some((row) => row.id === selectedClusterId.value)) {
    selectedClusterId.value = clusterList[0]?.id || null
  }
  const zoneList = childrenRows(selectedClusterId.value)
  if (!zoneList.some((row) => row.id === selectedZoneId.value)) {
    selectedZoneId.value = zoneList[0]?.id || null
  }
  const leafList = childrenRows(selectedZoneId.value)
  if (!leafList.some((row) => row.id === selectedLeafId.value)) {
    selectedLeafId.value = null
  }
}

watch(() => props.rows, pickDefaults, { immediate: true })

function selectCluster(row) {
  selectedClusterId.value = row.id
  selectedZoneId.value = childrenRows(row.id)[0]?.id || null
  selectedLeafId.value = null
  facet.value = 'school'
}

function selectZone(row) {
  selectedZoneId.value = row.id
  selectedLeafId.value = null
  facet.value = 'school'
}

function selectFacet(next) {
  facet.value = next
  const list = next === 'school' ? schools.value : teams.value
  selectedLeafId.value = list[0]?.id || null
}

function selectLeaf(row) {
  selectedLeafId.value = row.id
}

const breadcrumbChain = computed(() => {
  const anchorId = selectedLeafId.value || selectedZoneId.value || selectedClusterId.value
  const chain = []
  let current = anchorId ? rowMap.value.get(anchorId) : null
  while (current) {
    chain.unshift(current)
    current = current.parent_id ? rowMap.value.get(current.parent_id) : null
  }
  return chain
})

function isCrumbNavigable(row) {
  return ['cluster', 'zone', 'high_school', 'team'].includes(row.level)
}

function goToCrumb(row) {
  if (row.level === 'cluster') selectCluster(row)
  else if (row.level === 'zone') selectZone(row)
  else selectLeaf(row)
}

function expandToLocations() {
  selectedClusterId.value = null
  selectedZoneId.value = null
  selectedLeafId.value = null
  pickDefaults()
}

function collapseAll() {
  selectedZoneId.value = null
  selectedLeafId.value = null
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

const visibleSchools = computed(() => schools.value.filter((row) => row.high_school_id))
const allVisibleSchoolsSelected = computed(
  () => Boolean(visibleSchools.value.length) && visibleSchools.value.every((row) => props.selectedSchoolIds.includes(row.high_school_id)),
)
const someVisibleSchoolsSelected = computed(
  () => visibleSchools.value.some((row) => props.selectedSchoolIds.includes(row.high_school_id)),
)

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
