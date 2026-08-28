<template>
  <section
    class="rounded-xl border border-outline-gray-2/80 bg-surface-white shadow-xs overflow-hidden"
    :aria-label="title || __('Danh sách hồ sơ')"
  >
    <header class="flex items-center justify-between border-b border-outline-gray-1 px-5 py-3.5">
      <div class="flex items-center gap-2.5">
        <h2 class="text-sm font-semibold text-ink-gray-9">
          {{ title || __('Danh sách hồ sơ') }}
        </h2>
        <Badge
          v-if="rows.length"
          variant="subtle"
          theme="gray"
          :label="String(rows.length)"
        />
      </div>

      <div class="flex items-center gap-2">
        <span
          v-if="stale"
          class="flex items-center gap-1 text-xs text-amber-700 font-medium"
          role="status"
        >
          <FeatherIcon name="loader" class="size-3 animate-spin" />
          {{ __('Đang cập nhật...') }}
        </span>
        <Button
          v-if="exportAction"
          variant="subtle"
          size="sm"
          iconLeft="download"
          :label="__('Xuất file')"
          @click="$emit('export')"
        />
      </div>
    </header>

    <div
      v-if="loading && !rows.length"
      class="flex items-center justify-center py-12 text-sm text-ink-gray-5 gap-2"
      role="status"
    >
      <FeatherIcon name="loader" class="size-4 animate-spin text-ink-gray-4" />
      <span>{{ __('Đang tải dữ liệu…') }}</span>
    </div>

    <div
      v-else-if="!rows.length"
      class="flex flex-col items-center justify-center py-12 text-center text-sm text-ink-gray-5"
    >
      <FeatherIcon name="user-x" class="size-8 text-ink-gray-4 mb-2 opacity-50" />
      <p>{{ emptyMessage || __('Không có hồ sơ nào phù hợp với bộ lọc.') }}</p>
    </div>

    <template v-else>
      <div class="hidden overflow-x-auto md:block">
        <table class="w-full text-xs sm:text-sm">
          <thead class="bg-surface-gray-2 text-left text-ink-gray-6 font-semibold uppercase tracking-wider text-[11px]">
            <tr>
              <th
                v-for="column in columns"
                :key="column.key"
                class="px-4 py-3"
              >
                {{ __(column.label) }}
              </th>
              <th class="px-4 py-3 text-right">
                <span class="sr-only">{{ __('Hành động') }}</span>
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-outline-gray-1">
            <tr
              v-for="row in rows"
              :key="row.id || row.name"
              class="transition-colors hover:bg-surface-gray-1/60"
            >
              <td
                v-for="column in columns"
                :key="column.key"
                class="px-4 py-3 text-ink-gray-8"
              >
                {{ displayCell(row, column) }}
              </td>
              <td class="px-4 py-3 text-right">
                <Button
                  v-if="row.drillDown"
                  variant="ghost"
                  size="sm"
                  iconRight="chevron-right"
                  :label="__('Mở')"
                  @click="$emit('open', row)"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="divide-y divide-outline-gray-1 md:hidden">
        <article
          v-for="row in rows"
          :key="row.id || row.name"
          class="p-4 transition-colors hover:bg-surface-gray-1/40"
        >
          <dl class="grid grid-cols-2 gap-x-4 gap-y-3">
            <template v-for="column in columns" :key="column.key">
              <dt class="text-xs font-medium text-ink-gray-5">
                {{ __(column.label) }}
              </dt>
              <dd class="text-sm text-ink-gray-8">
                {{ displayCell(row, column) }}
              </dd>
            </template>
          </dl>
          <div v-if="row.drillDown" class="mt-3 flex justify-end">
            <Button
              variant="subtle"
              size="sm"
              iconRight="chevron-right"
              :label="__('Mở hồ sơ')"
              @click="$emit('open', row)"
            />
          </div>
        </article>
      </div>

      <div
        v-if="nextCursor"
        class="border-t border-outline-gray-1 p-3.5 text-center bg-surface-gray-1/30"
      >
        <Button
          variant="subtle"
          size="sm"
          :disabled="loading"
          :loading="loading"
          :label="loading ? __('Đang tải…') : __('Tải thêm')"
          @click="$emit('load-more')"
        />
      </div>
    </template>
  </section>
</template>

<script setup>
import { Badge, Button, FeatherIcon } from 'frappe-ui'

defineProps({
  rows: { type: Array, default: () => [] },
  columns: { type: Array, default: () => [] },
  title: String,
  loading: Boolean,
  stale: Boolean,
  nextCursor: String,
  emptyMessage: String,
  exportAction: Object,
})

defineEmits(['open', 'load-more', 'export'])

function displayCell(row, column) {
  return column.redaction === 'redacted' || row[`${column.key}Redacted`]
    ? __('Bị ẩn')
    : row[column.key] ?? '—'
}
</script>
