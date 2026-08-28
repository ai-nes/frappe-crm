<template>
  <div v-if="loading && !hasData" class="flex min-h-60 items-center justify-center" role="status">
    <LoadingIndicator class="size-6" />
    <span class="sr-only">{{ __('Đang tải dữ liệu nhóm...') }}</span>
  </div>
  <div v-else-if="error" class="mx-auto mt-10 w-full max-w-lg rounded-lg border border-red-200 bg-red-50 p-5" role="alert">
    <p class="font-medium text-ink-gray-9">{{ __('Không thể tải dữ liệu nhóm') }}</p>
    <p class="mt-1 text-sm text-ink-gray-6">{{ error }}</p>
    <Button class="mt-4" :label="__('Thử lại')" @click="$emit('retry')" />
  </div>
  <slot v-else />
</template>

<script setup>
import { Button, LoadingIndicator } from 'frappe-ui'

defineProps({ loading: Boolean, error: { type: [String, Error], default: '' }, hasData: Boolean })
defineEmits(['retry'])
</script>
