<template>
  <section class="space-y-4" data-testid="assignment-load-balance">
    <div class="flex justify-end">
      <Button
        variant="subtle"
        size="sm"
        :label="__('Làm mới')"
        iconLeft="refresh-cw"
        :loading="loading"
        @click="$emit('refresh')"
      />
    </div>

    <div
      v-if="staffLoad.length"
      class="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-blue-100 bg-blue-50/50 px-4 py-3 text-sm"
      data-testid="assignment-load-summary"
    >
      <span class="font-medium text-ink-gray-8">{{
        __('Mỗi người nhận Lead theo giới hạn riêng.')
      }}</span>
      <span class="text-orange-700"
        >{{ loadSummary.unconfigured }} {{ __('chưa đặt giới hạn') }}</span
      >
      <span class="text-orange-700"
        >{{ loadSummary.near_capacity }} {{ __('gần đầy') }}</span
      >
      <span class="text-red-700"
        >{{ loadSummary.over_capacity }} {{ __('vượt giới hạn') }}</span
      >
    </div>

    <div
      class="overflow-x-auto rounded-xl border border-outline-gray-2 bg-surface-white shadow-sm"
    >
      <table class="w-full min-w-[1060px] text-sm">
        <thead class="bg-surface-gray-1 text-left text-xs text-ink-gray-6">
          <tr>
            <th class="px-4 py-3">{{ __('Nhân viên tư vấn') }}</th>
            <th class="px-4 py-3">{{ __('Vai trò') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Đang có') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Giới hạn Lead') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Còn trống') }}</th>
            <th class="w-56 px-4 py-3">{{ __('Đã dùng') }}</th>
            <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Thao tác') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in sortedStaffLoad"
            :key="`${row.staff}-${row.team}`"
            class="border-t border-outline-gray-1 align-top"
          >
            <td class="px-4 py-3">
              <p class="font-medium text-ink-gray-9">{{ row.staff_name }}</p>
              <p class="mt-0.5 text-xs text-ink-gray-5">
                {{ (row.team_names || [row.team_name]).join(' · ') }} ·
                {{ row.campus_name || row.campus || '—' }}
              </p>
            </td>
            <td class="px-4 py-3 text-ink-gray-7">
              <span v-if="row.recipient_eligible" class="text-green-700">{{
                row.function || __('Sale')
              }}</span>
              <span v-else class="text-ink-gray-5">{{
                row.function || __('Không xác định')
              }}</span>
            </td>
            <td class="px-4 py-3 text-right tabular-nums font-medium">
              {{ row.active_leads }}
            </td>
            <td class="px-4 py-3 text-right tabular-nums">
              <template v-if="editingStaff === row.staff">
                <FormControl
                  v-model="capacityDraft"
                  type="number"
                  min="1"
                  class="w-24 ml-auto"
                />
              </template>
              <template v-else>{{ row.capacity ?? '—' }}</template>
            </td>
            <td
              class="px-4 py-3 text-right tabular-nums"
              :class="
                row.remaining === 0
                  ? 'font-semibold text-orange-700'
                  : 'text-ink-gray-7'
              "
            >
              {{ row.remaining ?? '—' }}
            </td>
            <td class="px-4 py-3">
              <div
                v-if="
                  row.load_percent !== null && row.load_percent !== undefined
                "
              >
                <div class="flex items-center justify-between gap-2 text-xs">
                  <span>{{ row.load_percent }}%</span
                  ><span class="text-ink-gray-5">{{
                    workloadLabel(row.workload)
                  }}</span>
                </div>
                <div
                  class="mt-1 h-2 overflow-hidden rounded-full bg-surface-gray-2"
                >
                  <div
                    class="h-full rounded-full"
                    :class="barClass(row.workload)"
                    :style="{ width: `${Math.min(row.load_percent, 100)}%` }"
                  />
                </div>
              </div>
              <span v-else class="text-orange-700">{{
                __('Chưa đặt giới hạn')
              }}</span>
            </td>
            <td class="px-4 py-3">
              <Badge
                :label="workloadLabel(row.workload)"
                :theme="workloadTheme(row.workload)"
                variant="subtle"
              />
            </td>
            <td class="px-4 py-3 text-right">
              <template v-if="canManage && row.recipient_eligible">
                <div
                  v-if="editingStaff === row.staff"
                  class="flex justify-end gap-2"
                >
                  <Button
                    size="sm"
                    variant="solid"
                    :label="__('Lưu')"
                    :loading="saving"
                    @click="$emit('save-capacity', capacityPayload(row))"
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    :label="__('Huỷ')"
                    @click="cancelEdit"
                  />
                </div>
                <Button
                  v-else
                  size="sm"
                  variant="subtle"
                  :label="__('Đặt giới hạn Lead')"
                  iconLeft="edit-2"
                  @click="startEdit(row)"
                />
              </template>
              <span v-else class="text-xs text-ink-gray-5">{{
                row.recipient_eligible ? __('Chỉ xem') : __('Điều phối')
              }}</span>
            </td>
          </tr>
          <tr v-if="!staffLoad.length">
            <td
              colspan="8"
              class="px-4 py-10 text-center text-sm text-ink-gray-5"
            >
              {{ __('Chưa có nhân sự trong phạm vi hiển thị.') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { Badge, Button, FormControl } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  staffLoad: { type: Array, default: () => [] },
  loading: Boolean,
  saving: Boolean,
  canManage: Boolean,
})
defineEmits(['refresh', 'save-capacity'])
const editingStaff = ref('')
const capacityDraft = ref('')

const sortedStaffLoad = computed(() =>
  [...props.staffLoad].sort((a, b) => {
    const rank = {
      unconfigured: 0,
      over_capacity: 1,
      near_capacity: 2,
      healthy: 3,
    }
    return (rank[a.workload] ?? 4) - (rank[b.workload] ?? 4)
  }),
)
const loadSummary = computed(() => ({
  unconfigured: props.staffLoad.filter((row) => row.workload === 'unconfigured')
    .length,
  near_capacity: props.staffLoad.filter(
    (row) => row.workload === 'near_capacity',
  ).length,
  over_capacity: props.staffLoad.filter(
    (row) => row.workload === 'over_capacity',
  ).length,
}))

function startEdit(row) {
  editingStaff.value = row.staff
  capacityDraft.value = String(row.capacity || '')
}

function cancelEdit() {
  editingStaff.value = ''
  capacityDraft.value = ''
}

function capacityPayload(row) {
  return {
    staff: row.staff,
    team: row.team,
    max_active_students: capacityDraft.value,
    period_start: row.period_start,
    period_end: row.period_end,
    reason: `Cập nhật giới hạn Lead cho ${row.staff_name}`,
  }
}

function workloadLabel(value) {
  return (
    {
      unconfigured: __('Chưa đặt giới hạn'),
      healthy: __('Bình thường'),
      near_capacity: __('Gần đầy'),
      over_capacity: __('Vượt tải'),
    }[value] || '—'
  )
}
function workloadTheme(value) {
  return (
    {
      unconfigured: 'orange',
      healthy: 'green',
      near_capacity: 'orange',
      over_capacity: 'red',
    }[value] || 'gray'
  )
}
function barClass(value) {
  return (
    {
      healthy: 'bg-green-500',
      near_capacity: 'bg-orange-400',
      over_capacity: 'bg-red-500',
      unconfigured: 'bg-gray-300',
    }[value] || 'bg-gray-300'
  )
}
</script>
