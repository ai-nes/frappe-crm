<template>
  <div
    v-if="variant === 'page'"
    class="flex h-full overflow-hidden"
    aria-busy="true"
    role="status"
    :aria-label="__('Loading student details')"
  >
    <div class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div class="flex h-[45px] shrink-0 items-center gap-7 border-b px-5">
        <div
          v-for="index in 6"
          :key="index"
          class="h-4 w-16 animate-pulse rounded bg-surface-gray-2"
        />
      </div>
      <div class="flex flex-1 flex-col gap-5 overflow-hidden px-5 py-6">
        <div class="h-7 w-44 animate-pulse rounded bg-surface-gray-2" />
        <div class="grid gap-4 lg:grid-cols-2">
          <div v-for="index in 4" :key="index" class="rounded border p-5">
            <div class="h-4 w-24 animate-pulse rounded bg-surface-gray-2" />
            <div
              class="mt-4 h-5 w-3/4 animate-pulse rounded bg-surface-gray-2"
            />
            <div
              class="mt-3 h-4 w-1/2 animate-pulse rounded bg-surface-gray-2"
            />
          </div>
        </div>
      </div>
    </div>
    <aside class="flex w-[22rem] shrink-0 flex-col border-l">
      <div class="h-[45px] border-b px-5 py-3">
        <div class="h-5 w-36 animate-pulse rounded bg-surface-gray-2" />
      </div>
      <div class="space-y-5 border-b px-5 py-4">
        <div
          v-for="index in 3"
          :key="index"
          class="flex items-center justify-between gap-4"
        >
          <div class="h-4 w-24 animate-pulse rounded bg-surface-gray-2" />
          <div class="h-4 w-28 animate-pulse rounded bg-surface-gray-2" />
        </div>
      </div>
      <StudentDetailLoadingState variant="side-panel" />
    </aside>
  </div>
  <div
    v-else
    class="space-y-5 px-5 py-5"
    aria-busy="true"
    role="status"
    :aria-label="__('Loading student fields')"
  >
    <div
      v-for="section in 3"
      :key="section"
      class="space-y-4 border-b pb-5 last:border-b-0"
    >
      <div class="h-4 w-28 animate-pulse rounded bg-surface-gray-2" />
      <div
        v-for="field in 4"
        :key="field"
        class="flex items-center justify-between gap-4"
      >
        <div class="h-4 w-24 animate-pulse rounded bg-surface-gray-2" />
        <div class="h-4 w-32 animate-pulse rounded bg-surface-gray-2" />
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  variant: { type: String, default: 'page' },
})
</script>
