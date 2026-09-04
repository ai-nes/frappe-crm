<template>
  <Teleport to="body">
    <div v-if="row" class="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" :aria-label="__('Chi tiết cấu hình phân bổ')">
      <button class="absolute inset-0 cursor-default bg-black/20" type="button" :aria-label="__('Đóng')" @click="close" />
      <aside class="relative h-full w-full max-w-lg overflow-y-auto bg-surface-white shadow-xl">
        <div class="flex items-start justify-between border-b border-outline-gray-1 px-5 py-4">
          <div>
            <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ levelLabel(row.level) }}</p>
            <h2 class="mt-1 text-lg font-semibold text-ink-gray-9">{{ row.label }}</h2>
            <StatusChip class="mt-2" :status="row.status" />
          </div>
          <div class="flex items-center gap-2">
            <Button
              v-if="canEditRow"
              size="sm"
              variant="solid"
              :label="__('Chỉnh sửa')"
              iconLeft="edit-2"
              @click="edit"
            />
            <button type="button" class="rounded-md p-1.5 text-ink-gray-5 hover:bg-surface-gray-2 focus:outline-none focus:ring-2 focus:ring-outline-gray-4" :aria-label="__('Đóng')" @click="close">
              <FeatherIcon name="x" class="size-5" aria-hidden="true" />
            </button>
          </div>
        </div>
        <div class="space-y-5 p-5">
          <section>
            <h3 class="text-sm font-semibold text-ink-gray-9">{{ __('Cấu hình hiện tại') }}</h3>
            <dl class="mt-3 grid gap-3 text-sm sm:grid-cols-2">
              <div v-for="item in details" :key="item.label">
                <dt class="text-xs text-ink-gray-5">{{ item.label }}</dt>
                <dd class="mt-0.5 break-words font-medium text-ink-gray-8">{{ item.value || '—' }}</dd>
              </div>
            </dl>
          </section>

          <section class="rounded-md border border-blue-100 bg-blue-50/60 p-3 text-sm text-blue-900">
            <div class="flex gap-2">
              <FeatherIcon name="info" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p>{{ explanation }}</p>
            </div>
          </section>

          <section v-if="row.level === 'high_school' || row.level === 'staff'" class="border-t border-outline-gray-1 pt-4">
            <h3 class="text-sm font-semibold text-ink-gray-9">{{ __('Mở nguồn dữ liệu') }}</h3>
            <div class="mt-3 flex flex-wrap gap-2">
              <RouterLink
                v-if="row.high_school_id"
                class="rounded-md border border-outline-gray-2 px-3 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50"
                :to="{ name: 'High School', params: { highSchoolId: row.high_school_id } }"
              >
                {{ __('Mở hồ sơ trường') }}
              </RouterLink>
              <RouterLink
                v-if="row.staff_id"
                class="rounded-md border border-outline-gray-2 px-3 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50"
                :to="{ name: 'CRM Staff', query: { staff: row.staff_id } }"
              >
                {{ __('Mở CRM Staff') }}
              </RouterLink>
            </div>
          </section>

          <p class="border-t border-outline-gray-1 pt-4 text-xs text-ink-gray-5">
            {{ canEditRow ? __('Chỉnh sửa sẽ mở preview ảnh hưởng và yêu cầu xác nhận trước khi ghi.') : __('Thay đổi phân bổ phải dùng command có kiểm tra quyền, hiệu lực, revision và lý do. Không sửa trực tiếp các cột owner/team/pool trong bảng này.') }}
          </p>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import { Button, FeatherIcon } from 'frappe-ui'
import StatusChip from './StatusChip.vue'

const props = defineProps({
  row: { type: Object, default: null },
  canEdit: Boolean,
})
const emit = defineEmits(['close', 'edit'])

const levelLabels = {
  campus: 'Campus',
  province: 'Tỉnh/TP',
  cluster: 'Cluster',
  zone: 'Zone',
  high_school: 'Trường THPT',
  team: 'Team',
  staff: 'Staff',
}

const levelLabel = (value) => levelLabels[value] || value
const canEditRow = computed(() => props.canEdit && ['zone', 'high_school'].includes(props.row?.level))
const details = computed(() => {
  const row = props.row || {}
  return [
    { label: __('Tỉnh/TP'), value: row.province_name || row.province_id },
    { label: __('Zone'), value: row.zone_name || row.zone_id },
    { label: __('Nhóm'), value: row.team_names?.join(', ') || row.team_name },
    { label: __('Nhân viên'), value: row.staff_names?.join(', ') || row.staff_name },
    { label: __('Pool'), value: row.pool_names?.join(', ') },
    { label: __('Hồ sơ đang hoạt động'), value: row.active_students },
    { label: __('Capacity'), value: row.capacity },
    { label: __('Tải'), value: row.load_percent === null || row.load_percent === undefined ? row.workload : `${row.load_percent}%` },
    { label: __('Revision'), value: row.revision },
    { label: __('Có hiệu lực từ'), value: row.effective_from },
  ]
})

const explanation = computed(() => {
  if (props.row?.status === 'unassigned') return __('Dòng này chưa có đủ Team/Staff/Pool để routing tự động chọn người nhận.')
  if (props.row?.status === 'needs_review') return __('Mapping hiện có nhưng đang bị đánh dấu cần rà soát, thường do Zone/Team thay đổi hoặc dữ liệu chưa đồng nhất.')
  if (props.row?.status === 'placeholder_zone') return __('Zone hiện là zone tạm/phụ trợ. Cần thay bằng geography chính thức trước khi bật routing production.')
  if (props.row?.status === 'capacity_warning') return __('Nhân sự đã gần hoặc vượt giới hạn tải đang cấu hình. Hãy kiểm tra Capacity trước khi nhận thêm lead.')
  return __('Mapping hiện tại đủ thông tin để routing sử dụng theo policy và pool đang hiệu lực.')
})

function close() {
  emit('close')
}

function edit() {
  if (canEditRow.value) emit('edit', props.row)
}

</script>
