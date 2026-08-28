<template>
  <section
    class="rounded-xl border border-outline-gray-2/80 bg-surface-white shadow-xs overflow-hidden"
    :aria-label="title || __('Yêu cầu phê duyệt')"
  >
    <header class="flex items-center justify-between border-b border-outline-gray-1 px-5 py-3.5">
      <div class="flex items-center gap-2.5">
        <h2 class="text-sm font-semibold text-ink-gray-9">
          {{ title || __('Yêu cầu phê duyệt') }}
        </h2>
        <Badge
          v-if="items.length"
          variant="subtle"
          theme="orange"
          :label="String(items.length)"
        />
      </div>
    </header>

    <div
      v-if="!items.length"
      class="flex flex-col items-center justify-center py-12 text-center text-sm text-ink-gray-5"
    >
      <FeatherIcon name="check-circle" class="size-8 text-green-500 mb-2 opacity-60" />
      <p>{{ emptyMessage || __('Không có yêu cầu phê duyệt nào đang chờ xử lý.') }}</p>
    </div>

    <ul v-else class="divide-y divide-outline-gray-1">
      <li
        v-for="item in items"
        :key="item.id || item.name"
        class="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between transition-colors hover:bg-surface-gray-1/40"
      >
        <div class="space-y-1">
          <div class="flex items-center gap-2">
            <p class="font-medium text-sm text-ink-gray-9">
              {{ item.title || item.action || item.name }}
            </p>
            <Badge
              v-if="item.priority"
              variant="subtle"
              :theme="item.priority === 'urgent' || item.priority === 'high' ? 'red' : 'gray'"
              :label="item.priority"
            />
          </div>
          <p v-if="item.description || item.reason" class="text-xs text-ink-gray-6">
            {{ item.description || item.reason }}
          </p>
          <p v-if="item.age" class="text-[11px] text-ink-gray-5 flex items-center gap-1">
            <FeatherIcon name="clock" class="size-3" />
            <span>{{ __('Thời gian chờ: {0}', [item.age]) }}</span>
          </p>
        </div>

        <div v-if="permittedActions(item).length" class="flex items-center gap-2 shrink-0">
          <Button
            v-for="action in permittedActions(item)"
            :key="action.key || action.token"
            :variant="action.variant || 'subtle'"
            size="sm"
            :loading="busy === (item.id || item.name)"
            :disabled="Boolean(busy && busy !== (item.id || item.name))"
            :label="action.label"
            @click="decide(item, action)"
          />
        </div>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { Badge, Button, FeatherIcon } from 'frappe-ui'
import { ref } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  title: String,
  emptyMessage: String,
  onDecision: Function,
})

const emit = defineEmits(['decided', 'error'])
const busy = ref('')

function permittedActions(item) {
  return (item.actions || []).filter(
    (action) => action?.token || action?.handoffToken,
  )
}

async function decide(item, action) {
  if (!action?.token && !action?.handoffToken) return
  if (!props.onDecision) return emit('decided', { item, action })
  busy.value = item.id || item.name
  try {
    await props.onDecision(item, action)
    emit('decided', { item, action })
  } catch (error) {
    emit('error', error)
  } finally {
    busy.value = ''
  }
}
</script>
