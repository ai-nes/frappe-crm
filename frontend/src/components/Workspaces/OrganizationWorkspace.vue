<template>
  <section
    class="rounded-xl border border-outline-gray-2/80 bg-surface-white shadow-xs overflow-hidden"
    :aria-label="title || __('Cơ cấu tổ chức')"
  >
    <header class="border-b border-outline-gray-1 px-5 py-3.5">
      <h2 class="text-sm font-semibold text-ink-gray-9">
        {{ title || __('Cơ cấu tổ chức') }}
      </h2>
      <p v-if="description" class="mt-0.5 text-xs text-ink-gray-6">
        {{ description }}
      </p>
    </header>

    <div
      v-if="!items.length"
      class="flex flex-col items-center justify-center py-12 text-center text-sm text-ink-gray-5"
      role="status"
    >
      <FeatherIcon name="layers" class="size-8 text-ink-gray-4 mb-2 opacity-50" />
      <p>{{ emptyMessage || __('Chưa có dữ liệu cơ cấu tổ chức cho chế độ xem này.') }}</p>
    </div>

    <template v-else>
      <div class="hidden overflow-x-auto md:block">
        <table class="w-full text-xs sm:text-sm">
          <thead class="bg-surface-gray-2 text-left text-ink-gray-6 font-semibold uppercase tracking-wider text-[11px]">
            <tr>
              <th class="px-4 py-3">{{ __('Tên') }}</th>
              <th class="px-4 py-3">{{ __('Loại') }}</th>
              <th class="px-4 py-3">{{ __('Thành viên') }}</th>
              <th class="px-4 py-3">{{ __('Phạm vi hiệu lực') }}</th>
              <th class="px-4 py-3 text-right">
                <span class="sr-only">{{ __('Quản lý') }}</span>
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-outline-gray-1">
            <tr
              v-for="item in items"
              :key="itemKey(item)"
              class="transition-colors hover:bg-surface-gray-1/60"
            >
              <td class="px-4 py-3 font-medium text-ink-gray-9">
                {{ item.name || item.label || '—' }}
              </td>
              <td class="px-4 py-3 text-ink-gray-7">{{ item.type || '—' }}</td>
              <td class="px-4 py-3 tabular-nums text-ink-gray-7">
                {{ membershipLabel(item) }}
              </td>
              <td class="px-4 py-3 text-ink-gray-7">{{ item.scopeSummary || '—' }}</td>
              <td class="px-4 py-3 text-right"><DelegatedLink :item="item" /></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="divide-y divide-outline-gray-1 md:hidden">
        <article
          v-for="item in items"
          :key="itemKey(item)"
          class="p-4 transition-colors hover:bg-surface-gray-1/40"
        >
          <h3 class="font-medium text-ink-gray-9">{{ item.name || item.label || '—' }}</h3>
          <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5">
            <div>
              <dt class="text-xs text-ink-gray-5">{{ __('Loại') }}</dt>
              <dd class="mt-0.5 text-sm text-ink-gray-8">{{ item.type || '—' }}</dd>
            </div>
            <div>
              <dt class="text-xs text-ink-gray-5">{{ __('Thành viên') }}</dt>
              <dd class="mt-0.5 text-sm text-ink-gray-8">{{ membershipLabel(item) }}</dd>
            </div>
            <div class="col-span-2">
              <dt class="text-xs text-ink-gray-5">{{ __('Phạm vi hiệu lực') }}</dt>
              <dd class="mt-0.5 text-sm text-ink-gray-8">{{ item.scopeSummary || '—' }}</dd>
            </div>
          </dl>
          <div v-if="item.manageUrl" class="mt-3">
            <DelegatedLink :item="item" />
          </div>
        </article>
      </div>
    </template>
  </section>
</template>

<script>
export function organizationMembershipLabel(item = {}) {
  const count = item.memberCount ?? item.membershipCount
  return Number.isFinite(count) ? String(count) : '—'
}
</script>

<script setup>
import { computed, defineComponent, h } from 'vue'
import { FeatherIcon } from 'frappe-ui'
import { safeInternalUrl } from '@/utils/safeInternalUrl'

defineProps({
  title: String,
  description: String,
  items: { type: Array, default: () => [] },
  emptyMessage: String,
})

const DelegatedLink = defineComponent({
  props: { item: { type: Object, required: true } },
  setup(linkProps) {
    const label = computed(() => linkProps.item.manageLabel || __('Mở cài đặt đã duyệt'))
    const href = computed(() => safeInternalUrl(linkProps.item.manageUrl))
    return () =>
      href.value
        ? h(
            'a',
            {
              href: href.value,
              target: '_blank',
              rel: 'noopener noreferrer',
              class:
                'inline-flex items-center gap-1 text-xs font-medium text-ink-gray-8 hover:text-ink-gray-9 underline focus:outline-none focus:ring-2 focus:ring-outline-gray-4',
            },
            label.value,
          )
        : null
  },
})

function itemKey(item) {
  return item.id || item.key || item.name || item.label
}
function membershipLabel(item) {
  return organizationMembershipLabel(item)
}
</script>
