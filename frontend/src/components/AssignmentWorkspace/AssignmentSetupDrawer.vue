<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 z-40 flex justify-end"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="drawerTitleId"
    >
      <button
        class="absolute inset-0 cursor-default bg-black/20"
        type="button"
        :aria-label="__('Đóng')"
        @click="close"
      />
      <aside class="relative h-full w-full max-w-xl overflow-y-auto bg-surface-white shadow-xl">
        <div class="flex items-start justify-between gap-4 border-b border-outline-gray-1 px-5 py-4">
          <div>
            <p class="text-xs font-medium uppercase tracking-wide text-ink-gray-5">
              {{ __('Hướng dẫn') }}
            </p>
            <h2 :id="drawerTitleId" class="mt-1 text-lg font-semibold text-ink-gray-9">
              {{ __('Các bước setup') }}
            </h2>
            <p class="mt-1 text-sm text-ink-gray-6">
              {{ __('Để Lead mới được phân công đúng người.') }}
            </p>
          </div>
          <button
            ref="closeButton"
            type="button"
            class="inline-flex min-h-10 min-w-10 shrink-0 items-center justify-center rounded-md text-ink-gray-5 hover:bg-surface-gray-2 hover:text-ink-gray-9 focus:outline-none focus:ring-2 focus:ring-outline-gray-4"
            :aria-label="__('Đóng')"
            @click="close"
          >
            <FeatherIcon name="x" class="size-5" aria-hidden="true" />
          </button>
        </div>

        <div class="p-5">
          <AssignmentSetupPanel
            workflow-only
            :data="data"
            :control="control"
            :loading="loading"
            :error="error"
            :can-manage="canManage"
            @refresh="$emit('refresh')"
            @navigate="handleNavigate"
          />
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { FeatherIcon } from 'frappe-ui'
import AssignmentSetupPanel from './AssignmentSetupPanel.vue'

const show = defineModel({ type: Boolean })
defineProps({
  data: { type: Object, default: null },
  control: { type: Object, default: null },
  loading: Boolean,
  error: { type: [Object, String], default: null },
  canManage: Boolean,
})
const emit = defineEmits(['refresh', 'navigate'])
const drawerTitleId = 'assignment-setup-drawer-title'
const closeButton = ref(null)

function close() {
  show.value = false
}

function handleNavigate(tab) {
  close()
  emit('navigate', tab)
}

function handleKeydown(event) {
  if (event.key === 'Escape' && show.value) close()
}

watch(show, async (value) => {
  if (!value) return
  await nextTick()
  closeButton.value?.focus()
})

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>
