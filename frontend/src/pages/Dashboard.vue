<template>
  <div class="flex h-full flex-col overflow-hidden">
    <LayoutHeader>
      <template #left-header>
        <div class="flex items-center gap-2">
          <ViewBreadcrumbs :routeName="breadcrumbRouteName" />
          <Badge variant="subtle" theme="orange" :label="__('Mock data')" />
        </div>
      </template>
      <template #right-header>
        <Button
          :label="__('Refresh')"
          :iconLeft="LucideRefreshCcw"
          :loading="refreshing"
          @click="refreshDashboard"
        />
      </template>
    </LayoutHeader>

    <div class="flex flex-wrap items-center gap-3 px-5 pb-2 pt-5">
      <div
        v-if="isSalesDashboard"
        class="flex items-center rounded-md bg-surface-gray-2 p-0.5"
      >
        <Button
          v-for="section in salesSections"
          :key="section.value"
          :variant="activeSalesSection === section.value ? 'solid' : 'ghost'"
          :label="__(section.label)"
          @click="openSalesSection(section.value)"
        />
      </div>
      <div
        v-if="isOfflineMarketingDashboard"
        class="flex items-center rounded-md bg-surface-gray-2 p-0.5"
      >
        <Button
          v-for="team in offlineTeams"
          :key="team.value"
          :variant="offlineTeamFilter === team.value ? 'solid' : 'ghost'"
          :label="__(team.label)"
          @click="offlineTeamFilter = team.value"
        />
      </div>
      <Dropdown
        v-if="!showDatePicker"
        v-model="preset"
        :options="options"
        class="form-control"
        :placeholder="__('Select Range')"
        :button="{
          label: __(preset),
          class:
            '!w-full justify-start [&>span]:mr-auto [&>svg]:text-ink-gray-5',
          variant: 'outline',
          iconRight: 'chevron-down',
          iconLeft: 'calendar',
        }"
      />
      <DateRangePicker
        v-else
        ref="datePickerRef"
        class="!w-48"
        :value="filters.period"
        variant="outline"
        :placeholder="__('Period')"
        :formatter="formatRange"
        @change="setCustomRange"
      >
        <template #prefix>
          <LucideCalendar class="mr-2 size-4 text-ink-gray-5" />
        </template>
      </DateRangePicker>
      <Link
        v-if="isSalesDashboard && (isAdmin() || isManager())"
        class="form-control w-48"
        variant="outline"
        :value="filters.user && getUser(filters.user).full_name"
        doctype="User"
        :filters="{
          name: ['in', users.data.crmUsers?.map((user) => user.name)],
          ignore_user_type: 1,
        }"
        :placeholder="__('Sales User')"
        :hideMe="true"
        @change="(value) => updateFilter('user', value)"
      >
        <template #prefix>
          <UserAvatar
            v-if="filters.user"
            class="mr-2"
            :user="filters.user"
            size="sm"
          />
        </template>
        <template #item-prefix="{ option }">
          <UserAvatar class="mr-2" :user="option.value" size="sm" />
        </template>
        <template #item-label="{ option }">
          <Tooltip :text="option.value">
            <div class="cursor-pointer">
              {{ getUser(option.value).full_name }}
            </div>
          </Tooltip>
        </template>
      </Link>
      <Button
        :label="advancedFilterLabel"
        :iconLeft="LucideListFilter"
        @click="showAdvancedFilters = true"
      />
    </div>

    <div class="flex min-h-0 flex-1 flex-col overflow-hidden border-t">
      <DashboardGrid
        :key="`${props.dashboardType}-${activeSalesSection}-${offlineTeamFilter}-${renderKey}`"
        :model-value="dashboardItems"
        @refresh="refreshDashboard"
      />
    </div>
  </div>
  <Dialog
    v-model="showAdvancedFilters"
    :options="{ title: __('Dashboard Filters'), size: 'xl' }"
  >
    <template #body-content>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <FormControl
          v-for="field in dashboardFilterFields"
          :key="field.key"
          v-model="advancedFilters[field.key]"
          type="select"
          :label="__(field.label)"
          :options="field.options"
        />
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Clear Filters')" @click="clearAdvancedFilters" />
        <Button
          variant="solid"
          :label="__('Apply Filters')"
          @click="applyAdvancedFilters"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import DashboardGrid from '@/components/Dashboard/DashboardGrid.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import Link from '@/components/Controls/Link.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import {
  digitalMarketingDashboardItems,
  offlineMarketingDashboardItems,
  salesDashboardSections,
  type OfflineTeam,
} from '@/data/admissionsDashboardMock'
import { usersStore } from '@/stores/users'
import { formatRange, formatter, getLastXDays } from '@/utils/dashboard'
import {
  Badge,
  DateRangePicker,
  Dialog,
  Dropdown,
  FormControl,
  Tooltip,
  usePageMeta,
} from 'frappe-ui'
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import LucideCalendar from '~icons/lucide/calendar'
import LucideListFilter from '~icons/lucide/list-filter'
import LucideRefreshCcw from '~icons/lucide/refresh-ccw'

const { users, getUser, isManager, isAdmin } = usersStore()
const props = defineProps({
  dashboardType: { type: String, default: 'sales' },
  dashboardSection: { type: String, default: 'overview' },
})
const router = useRouter()

const refreshing = ref(false)
const renderKey = ref(0)
const showDatePicker = ref(false)
const showAdvancedFilters = ref(false)
const datePickerRef = ref()
const preset = ref('Last 30 Days')
const filters = reactive<{ period: string | null; user: string | null }>({
  period: getLastXDays(),
  user: null,
})

const advancedFilters = reactive<Record<string, string>>({})
const advancedFilterFields = [
  { key: 'admissionTerm', label: 'Admission Term', options: ['2026', '2026–2027', '2027'] },
  { key: 'campus', label: 'Campus', options: ['Hà Nội', 'TP. Hồ Chí Minh', 'Đà Nẵng', 'Cần Thơ', 'Quy Nhơn'] },
  { key: 'program', label: 'Program', options: ['Công nghệ thông tin', 'Quản trị kinh doanh', 'Thiết kế mỹ thuật số', 'Truyền thông đa phương tiện'] },
  { key: 'province', label: 'Province', options: ['Hà Nội', 'TP. Hồ Chí Minh', 'Đà Nẵng', 'Cần Thơ', 'An Giang'] },
  { key: 'district', label: 'District', options: ['Nội thành', 'Ngoại thành', 'Ngoài tỉnh'] },
  { key: 'highSchool', label: 'High School', options: ['Tất cả trường THPT', 'THPT chuyên', 'THPT công lập', 'THPT tư thục'] },
  { key: 'salesTeam', label: 'Sales Team', options: ['Team North', 'Team Central', 'Team South'] },
  { key: 'leadChannel', label: 'Lead Channel', options: ['Digital', 'Event', 'Organic', 'Referral'] },
  { key: 'leadSource', label: 'Lead Source', options: ['Facebook', 'Google', 'Zalo', 'TikTok', 'Referral', 'Website'] },
  { key: 'campaign', label: 'Campaign', options: ['Open Day 2026', 'GenZ chọn ngành đúng', 'FPTU Scholarship', 'Campus Tour'] },
  { key: 'stage', label: 'Admission Stage', options: ['New Lead', 'Contacted', 'Qualified', 'Counseling', 'Application', 'Enrolled'] },
  { key: 'dimension', label: 'Interest Dimension', options: ['Chi phí', 'Ngành & trường khác', 'Việc làm', 'Hoạt động sinh viên', 'Chỗ ở', 'Quan tâm', 'Khác'] },
  { key: 'interestLevel', label: 'Interest Level', options: ['Level ≥1', 'Level ≥2', 'Level 3'] },
  { key: 'stance', label: 'Stance', options: ['POSITIVE', 'NEUTRAL', 'NEGATIVE', 'UNRESOLVED'] },
  { key: 'readiness', label: 'Readiness', options: ['Level 0', 'Level 1', 'Level 2', 'Level 3', 'Level 4'] },
  { key: 'confidence', label: 'Confidence Range', options: ['80–100', '60–79', 'Dưới 60'] },
  { key: 'freshness', label: 'Data Freshness', options: ['Fresh · ≤15 phút', 'Recent · 16–60 phút', 'Stale · >60 phút', 'Never analyzed'] },
  { key: 'newSignal', label: 'Has New Signal', options: ['Có', 'Không'] },
  { key: 'sla', label: 'SLA Status', options: ['Đúng SLA', 'Sắp quá hạn', 'Quá SLA'] },
]

const marketingFilterKeys = new Set([
  'admissionTerm',
  'campus',
  'program',
  'province',
  'district',
  'highSchool',
  'leadChannel',
  'leadSource',
  'campaign',
  'dimension',
  'interestLevel',
  'freshness',
])

const isSalesDashboard = computed(() => props.dashboardType === 'sales')
const isOfflineMarketingDashboard = computed(() => props.dashboardType === 'offline_marketing')
const salesSections = [
  { value: 'overview', label: 'Overview' },
  { value: 'interests', label: 'AI Interests' },
  { value: 'actions', label: 'Action Queue' },
] as const
type SalesSection = (typeof salesSections)[number]['value']
const activeSalesSection = computed<SalesSection>(() =>
  salesSections.some((section) => section.value === props.dashboardSection)
    ? (props.dashboardSection as SalesSection)
    : 'overview',
)
const offlineTeams = [
  { value: 'all', label: 'Tổng quan tất cả' },
  { value: 'Team North', label: 'Team North' },
  { value: 'Team Central', label: 'Team Central' },
  { value: 'Team South', label: 'Team South' },
] as const satisfies { value: OfflineTeam; label: string }[]
const offlineTeamFilter = ref<OfflineTeam>('all')
const dashboardItems = computed(() => {
  if (isSalesDashboard.value) return salesDashboardSections[activeSalesSection.value]
  if (isOfflineMarketingDashboard.value) return offlineMarketingDashboardItems(offlineTeamFilter.value)
  return digitalMarketingDashboardItems
})
const breadcrumbRouteName = computed(() => {
  if (isSalesDashboard.value) return 'Dashboard'
  if (isOfflineMarketingDashboard.value) return 'Offline Marketing Dashboard'
  return 'Digital Marketing Dashboard'
})
const dashboardFilterFields = computed(() =>
  isSalesDashboard.value
    ? advancedFilterFields
    : advancedFilterFields.filter((field) => marketingFilterKeys.has(field.key)),
)

const activeAdvancedFilterCount = computed(
  () => Object.values(advancedFilters).filter(Boolean).length,
)
const advancedFilterLabel = computed(() =>
  activeAdvancedFilterCount.value
    ? `${__('Filters')} (${activeAdvancedFilterCount.value})`
    : __('Filters'),
)

function presetOption(days: number, label: string) {
  return {
    label,
    onClick: () => {
      preset.value = `Last ${days} Days`
      filters.period = getLastXDays(days)
      renderKey.value += 1
    },
  }
}

const options = computed(() => [
  {
    group: 'Presets',
    hideLabel: true,
    items: [
      presetOption(7, __('Last 7 Days')),
      presetOption(30, __('Last 30 Days')),
      presetOption(60, __('Last 60 Days')),
      presetOption(90, __('Last 90 Days')),
    ],
  },
  {
    label: __('Custom Range'),
    onClick: () => {
      showDatePicker.value = true
      window.setTimeout(() => datePickerRef.value?.open(), 0)
      preset.value = 'Custom Range'
      filters.period = null
    },
  },
])

function updateFilter(key: 'user', value: string | null) {
  filters[key] = value
  renderKey.value += 1
}

function setCustomRange(value: string | null) {
  showDatePicker.value = false
  filters.period = value || getLastXDays()
  preset.value = value ? formatter(value) : 'Last 30 Days'
  renderKey.value += 1
}

function refreshDashboard() {
  refreshing.value = true
  window.setTimeout(() => {
    renderKey.value += 1
    refreshing.value = false
  }, 350)
}

function openSalesSection(section: SalesSection) {
  if (section !== activeSalesSection.value) {
    router.push({ name: 'Dashboard', params: { section } })
  }
}

function clearAdvancedFilters() {
  Object.keys(advancedFilters).forEach((key) => delete advancedFilters[key])
  renderKey.value += 1
}

function applyAdvancedFilters() {
  renderKey.value += 1
  showAdvancedFilters.value = false
}

usePageMeta(() => ({
  title: isSalesDashboard.value
    ? __('Sales Dashboard')
    : isOfflineMarketingDashboard.value
      ? __('Offline Marketing Dashboard')
      : __('Digital Marketing Dashboard'),
}))
</script>
