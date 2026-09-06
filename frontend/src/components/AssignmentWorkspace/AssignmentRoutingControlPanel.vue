<template>
  <section class="space-y-4" data-testid="assignment-routing-control">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="mt-1 text-xl font-semibold text-ink-gray-9">
          {{ __('Tự động phân công') }}
        </h2>
        <p class="mt-1 max-w-3xl text-sm text-ink-gray-6">
          {{ __('Lead mới sẽ được chia cho người còn chỗ trong đúng nhóm.') }}
        </p>
      </div>
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
      v-if="error"
      class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900"
      role="alert"
    >
      {{ errorMessage(error) }}
    </div>

    <div v-if="control" class="grid gap-4 xl:grid-cols-[1.1fr_1fr]">
      <div
        class="rounded-xl border border-outline-gray-2 bg-surface-white p-5 shadow-sm"
      >
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <span
              class="flex size-10 items-center justify-center rounded-full"
              :class="
                control.enabled
                  ? 'bg-green-50 text-green-700'
                  : 'bg-gray-100 text-ink-gray-5'
              "
            >
              <FeatherIcon
                :name="control.enabled ? 'play' : 'pause'"
                class="size-5"
                aria-hidden="true"
              />
            </span>
            <div>
              <p class="font-semibold text-ink-gray-9">
                {{ control.enabled ? __('Đang bật') : __('Đang tắt') }}
              </p>
              <p class="mt-0.5 text-xs text-ink-gray-5">
                {{
                  control.control_source === 'workspace'
                    ? __('Quản lý tại đây')
                    : __('Đang dùng thiết lập mặc định')
                }}
              </p>
            </div>
          </div>
          <Badge
            :label="control.enabled ? __('Đang bật') : __('Đang tắt')"
            :theme="control.enabled ? 'green' : 'gray'"
            variant="subtle"
          />
        </div>

        <div
          class="mt-5 rounded-lg border border-outline-gray-1 bg-surface-gray-1 p-3"
        >
          <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
            <p class="text-xs text-ink-gray-5">
              {{ __('Hệ thống tự lưu thao tác vào lịch sử thay đổi.') }}
            </p>
            <Button
              :variant="control.enabled ? 'subtle' : 'solid'"
              :theme="control.enabled ? 'red' : 'green'"
              :label="
                control.enabled ? __('Tắt phân công') : __('Bật phân công')
              "
              :disabled="
                !canManage || (!control.enabled && !control.ready_to_enable)
              "
              :loading="saving"
              :data-testid="
                control.enabled ? 'disable-routing' : 'enable-routing'
              "
              @click="$emit('toggle', { enabled: !control.enabled })"
            />
          </div>
        </div>
        <p v-if="!canManage" class="mt-3 text-xs text-orange-700">
          {{ __('Chỉ System Manager được thay đổi.') }}
        </p>
      </div>

      <div
        class="rounded-xl border border-outline-gray-2 bg-surface-white p-5 shadow-sm"
      >
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="text-sm font-semibold text-ink-gray-9">
              {{ __('Điều kiện') }}
            </p>
            <p class="mt-1 text-xs text-ink-gray-5">
              {{
                control.ready_to_enable
                  ? __('Đã đủ điều kiện vận hành.')
                  : __('Cần xử lý các mục màu cam trước.')
              }}
            </p>
          </div>
          <Badge
            :label="control.ready_to_enable ? __('Sẵn sàng') : __('Cần setup')"
            :theme="control.ready_to_enable ? 'green' : 'orange'"
            variant="subtle"
          />
        </div>
        <div class="mt-4 space-y-2">
          <div
            v-for="check in control.checks"
            :key="check.code"
            class="flex items-start gap-2 rounded-md border px-3 py-2 text-sm"
            :class="
              check.passed
                ? 'border-green-100 bg-green-50/50'
                : 'border-orange-100 bg-orange-50/60'
            "
          >
            <FeatherIcon
              :name="check.passed ? 'check-circle' : 'alert-circle'"
              class="mt-0.5 size-4 shrink-0"
              :class="check.passed ? 'text-green-600' : 'text-orange-600'"
              aria-hidden="true"
            />
            <div class="min-w-0">
              <p
                class="font-medium"
                :class="check.passed ? 'text-green-900' : 'text-orange-900'"
              >
                {{ check.label }}
              </p>
              <p
                class="mt-0.5 text-xs"
                :class="check.passed ? 'text-green-800' : 'text-orange-800'"
              >
                {{ check.detail }}
              </p>
              <button
                v-if="!check.passed"
                type="button"
                class="mt-2 text-xs font-medium text-blue-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                :data-testid="`assignment-check-${check.code}`"
                @click="$emit('navigate', checkTab(check.code))"
              >
                {{ __('Mở nơi thiết lập') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="control?.summary"
      class="grid gap-3 sm:grid-cols-2 xl:grid-cols-6"
    >
      <MetricCard
        :label="__('Người nhận đủ điều kiện')"
        :value="control.summary.eligible_staff"
      />
      <MetricCard
        :label="__('Đã đặt giới hạn')"
        :value="control.summary.capacity_configured"
        :tone="control.summary.capacity_missing ? 'warning' : 'default'"
      />
      <MetricCard
        :label="__('Lead đang giữ')"
        :value="control.summary.active_leads"
      />
      <MetricCard
        :label="__('Tổng Lead tối đa')"
        :value="control.summary.total_capacity"
      />
      <MetricCard
        :label="__('Còn trống')"
        :value="control.summary.remaining_capacity"
        :tone="control.summary.remaining_capacity ? 'success' : 'warning'"
      />
      <MetricCard
        :label="__('Gần/vượt giới hạn')"
        :value="`${control.summary.near_capacity}/${control.summary.over_capacity}`"
        :tone="control.summary.over_capacity ? 'warning' : 'default'"
      />
    </div>
  </section>
</template>

<script setup>
import { Badge, Button, FeatherIcon } from 'frappe-ui'

defineProps({
  control: { type: Object, default: null },
  loading: Boolean,
  saving: Boolean,
  error: { type: [Object, String], default: null },
  canManage: Boolean,
})
defineEmits(['refresh', 'toggle', 'navigate'])

function checkTab(code) {
  return (
    {
      active_policy: 'policy',
      eligible_staff: 'setup',
      capacity_configured: 'load',
    }[code] || 'setup'
  )
}

function errorMessage(error) {
  return (
    error?.messages?.join?.(' ') ||
    error?.message ||
    String(error || __('Không thể tải cấu hình.'))
  )
}

const MetricCard = {
  props: { label: String, value: [String, Number], tone: String },
  template: `<div class="rounded-lg border border-outline-gray-2 bg-surface-white px-3 py-3 shadow-sm"><p class="text-xs text-ink-gray-5">{{ label }}</p><p class="mt-1 text-xl font-semibold" :class="tone === 'warning' ? 'text-orange-700' : tone === 'success' ? 'text-green-700' : 'text-ink-gray-9'">{{ value ?? 0 }}</p></div>`,
}
</script>
