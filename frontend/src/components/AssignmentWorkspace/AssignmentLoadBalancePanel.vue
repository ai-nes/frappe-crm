<template>
  <section class="space-y-4" data-testid="assignment-load-balance">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="text-xs font-semibold uppercase tracking-wide text-ink-gray-5">{{ __('Cân bằng tải') }}</p>
        <h2 class="mt-1 text-xl font-semibold text-ink-gray-9">{{ __('Mỗi Sale đang giữ bao nhiêu Lead?') }}</h2>
        <p class="mt-1 text-sm text-ink-gray-6">{{ __('Capacity là số Lead hoạt động tối đa trong kỳ. Từ 85% là gần đầy, từ 100% sẽ không nhận thêm.') }}</p>
      </div>
      <Button variant="subtle" size="sm" :label="__('Làm mới tải')" iconLeft="refresh-cw" :loading="loading" @click="$emit('refresh')" />
    </div>

    <div class="overflow-x-auto rounded-xl border border-outline-gray-2 bg-surface-white shadow-sm">
      <table class="w-full min-w-[1060px] text-sm">
        <thead class="bg-surface-gray-1 text-left text-xs text-ink-gray-6">
          <tr>
            <th class="px-4 py-3">{{ __('Sale / Team') }}</th>
            <th class="px-4 py-3">{{ __('Vai trò nhận Lead') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Đang giữ') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Capacity') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Còn trống') }}</th>
            <th class="w-56 px-4 py-3">{{ __('Mức tải') }}</th>
            <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
            <th class="px-4 py-3 text-right">{{ __('Thao tác') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in staffLoad" :key="`${row.staff}-${row.team}`" class="border-t border-outline-gray-1 align-top">
            <td class="px-4 py-3">
              <p class="font-medium text-ink-gray-9">{{ row.staff_name }}</p>
              <p class="mt-0.5 text-xs text-ink-gray-5">{{ (row.team_names || [row.team_name]).join(' · ') }} · {{ row.campus_name || row.campus || '—' }}</p>
            </td>
            <td class="px-4 py-3 text-ink-gray-7">
              <span v-if="row.recipient_eligible" class="text-green-700">{{ row.function || __('Sale') }}</span>
              <span v-else class="text-ink-gray-5">{{ row.function || __('Không xác định') }}</span>
            </td>
            <td class="px-4 py-3 text-right tabular-nums font-medium">{{ row.active_leads }}</td>
            <td class="px-4 py-3 text-right tabular-nums">
              <template v-if="editingStaff === row.staff">
                <FormControl v-model="capacityDraft" type="number" min="1" class="w-24 ml-auto" />
              </template>
              <template v-else>{{ row.capacity ?? '—' }}</template>
            </td>
            <td class="px-4 py-3 text-right tabular-nums" :class="row.remaining === 0 ? 'font-semibold text-orange-700' : 'text-ink-gray-7'">{{ row.remaining ?? '—' }}</td>
            <td class="px-4 py-3">
              <div v-if="row.load_percent !== null && row.load_percent !== undefined">
                <div class="flex items-center justify-between gap-2 text-xs"><span>{{ row.load_percent }}%</span><span class="text-ink-gray-5">{{ workloadLabel(row.workload) }}</span></div>
                <div class="mt-1 h-2 overflow-hidden rounded-full bg-surface-gray-2"><div class="h-full rounded-full" :class="barClass(row.workload)" :style="{ width: `${Math.min(row.load_percent, 100)}%` }" /></div>
              </div>
              <span v-else class="text-orange-700">{{ __('Chưa đặt capacity') }}</span>
            </td>
            <td class="px-4 py-3"><Badge :label="workloadLabel(row.workload)" :theme="workloadTheme(row.workload)" variant="subtle" /></td>
            <td class="px-4 py-3 text-right">
              <template v-if="canManage && row.recipient_eligible">
                <div v-if="editingStaff === row.staff" class="flex justify-end gap-2">
                  <Button size="sm" variant="solid" :label="__('Lưu')" :loading="saving" @click="$emit('save-capacity', capacityPayload(row))" />
                  <Button size="sm" variant="ghost" :label="__('Huỷ')" @click="cancelEdit" />
                </div>
                <Button v-else size="sm" variant="subtle" :label="__('Đặt capacity')" iconLeft="edit-2" @click="startEdit(row)" />
              </template>
              <span v-else class="text-xs text-ink-gray-5">{{ row.recipient_eligible ? __('Chỉ xem') : __('Điều phối') }}</span>
            </td>
          </tr>
          <tr v-if="!staffLoad.length"><td colspan="8" class="px-4 py-10 text-center text-sm text-ink-gray-5">{{ __('Chưa có nhân sự trong phạm vi hiển thị.') }}</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { Badge, Button, FormControl } from 'frappe-ui'
import { ref } from 'vue'

defineProps({
  staffLoad: { type: Array, default: () => [] },
  loading: Boolean,
  saving: Boolean,
  canManage: Boolean,
})
defineEmits(['refresh', 'save-capacity'])
const editingStaff = ref('')
const capacityDraft = ref('')

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
    reason: `Cập nhật capacity cho ${row.staff_name}`,
  }
}

function workloadLabel(value) {
  return { unconfigured: __('Chưa đặt tải'), healthy: __('Bình thường'), near_capacity: __('Gần đầy'), over_capacity: __('Vượt tải') }[value] || '—'
}
function workloadTheme(value) {
  return { unconfigured: 'orange', healthy: 'green', near_capacity: 'orange', over_capacity: 'red' }[value] || 'gray'
}
function barClass(value) {
  return { healthy: 'bg-green-500', near_capacity: 'bg-orange-400', over_capacity: 'bg-red-500', unconfigured: 'bg-gray-300' }[value] || 'bg-gray-300'
}
</script>
