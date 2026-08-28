<template>
  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
    <component
      :is="kpi.drilldown ? 'button' : 'div'"
      v-for="kpi in kpis"
      :key="kpi.key || kpi.label"
      class="rounded-lg border border-outline-gray-2 bg-surface-white p-4 text-left shadow-sm transition hover:border-outline-gray-3 focus:outline-none focus:ring-2 focus:ring-outline-gray-5"
      :class="{ 'cursor-pointer': kpi.drilldown }"
      :aria-label="kpi.drilldown ? `${kpi.label}: ${kpi.value}` : undefined"
      @click="kpi.drilldown && $emit('drilldown', kpi.drilldown)"
    >
      <p class="text-sm text-ink-gray-6">{{ kpi.label }}</p>
      <p class="mt-2 text-2xl font-semibold text-ink-gray-9">{{ kpi.value ?? 0 }}</p>
      <p v-if="kpi.description" class="mt-1 text-xs text-ink-gray-5">{{ kpi.description }}</p>
    </component>
  </div>
</template>

<script setup>
defineProps({ kpis: { type: Array, default: () => [] } })
defineEmits(['drilldown'])
</script>
