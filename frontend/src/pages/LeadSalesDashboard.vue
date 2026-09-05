<template>
  <LayoutHeader>
    <template #left-header><ViewBreadcrumbs routeName="Lead Sales Dashboard" /></template>
    <template #right-header>
      <Button :label="__('Làm mới')" iconLeft="refresh-cw" :loading="resource.loading" @click="resource.reload()" />
    </template>
  </LayoutHeader>

  <main class="h-full overflow-y-auto bg-surface-gray-2/40 p-4 sm:p-5">
    <div class="mx-auto max-w-7xl space-y-5">
      <LeadSalesPageState :loading="resource.loading" :error="resource.error" :has-data="Boolean(data)" @retry="resource.reload()">
        <template v-if="data">
          <section>
            <h1 class="text-xl font-semibold text-ink-gray-9">{{ __('Bảng điều khiển nhóm') }}</h1>
            <LeadSalesDefinition class="mt-1" :definition="workspaceDefinition(data)" :timestamp="formatWorkspaceTimestamp(data)" />
          </section>

          <LeadSalesKpiGrid :kpis="workspaceKpis(data)" />
          <AssignmentPipeline />

          <div class="grid gap-5 lg:grid-cols-2">
            <section class="rounded-lg border border-outline-gray-2 bg-surface-white">
              <div class="border-b border-outline-gray-1 px-4 py-3"><h2 class="font-semibold">{{ __('Khối lượng theo tư vấn viên') }}</h2></div>
              <div v-if="workload.length" class="overflow-x-auto">
                <table class="w-full min-w-[320px] text-sm">
                  <thead class="bg-surface-gray-2 text-left text-ink-gray-6"><tr><th class="px-4 py-2">{{ __('Tư vấn viên') }}</th><th class="px-4 py-2 text-right">{{ __('Hồ sơ') }}</th></tr></thead>
                  <tbody><tr v-for="member in workload" :key="member.owner_staff || 'unassigned'" class="border-t border-outline-gray-1"><td class="px-4 py-3 font-medium">{{ member.owner_name || member.staff_name || member.owner_staff || __('Chưa phân công') }}</td><td class="px-4 py-3 text-right">{{ member.count ?? 0 }}</td></tr></tbody>
                </table>
              </div>
              <p v-else class="p-5 text-sm text-ink-gray-5">{{ __('Chưa có khối lượng được phân công trong nhóm.') }}</p>
            </section>

            <section class="rounded-lg border border-outline-gray-2 bg-surface-white">
              <div class="border-b border-outline-gray-1 px-4 py-3"><h2 class="font-semibold">{{ __('Trạng thái SLA') }}</h2></div>
              <div v-if="slaBuckets.length" class="divide-y divide-outline-gray-1"><div v-for="bucket in slaBuckets" :key="bucket.status" class="flex items-center justify-between px-4 py-3 text-sm"><span>{{ bucket.status || __('Chưa xác định') }}</span><span class="font-semibold">{{ bucket.count ?? 0 }}</span></div></div>
              <p v-else class="p-5 text-sm text-ink-gray-5">{{ __('Chưa có SLA trong phạm vi nhóm.') }}</p>
            </section>
          </div>
        </template>
        <p v-else class="py-20 text-center text-sm text-ink-gray-5">{{ __('Chưa có dữ liệu tổng quan của nhóm.') }}</p>
      </LeadSalesPageState>
    </div>
  </main>
</template>

<script setup>
import { computed } from 'vue'
import { Button } from 'frappe-ui'
import LayoutHeader from '@/components/LayoutHeader.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import AssignmentPipeline from '@/components/LeadSales/AssignmentPipeline.vue'
import LeadSalesDefinition from '@/components/LeadSales/LeadSalesDefinition.vue'
import LeadSalesKpiGrid from '@/components/LeadSales/LeadSalesKpiGrid.vue'
import LeadSalesPageState from '@/components/LeadSales/LeadSalesPageState.vue'
import { createLeadSalesWorkspaceResource, formatWorkspaceTimestamp, workspaceDefinition, workspaceKpis, workspaceRows } from '@/data/leadSalesWorkspace'

const resource = createLeadSalesWorkspaceResource('dashboard')
const data = computed(() => resource.data)
const workload = computed(() => workspaceRows(data.value, 'workload'))
const slaBuckets = computed(() => workspaceRows(data.value, 'sla_buckets'))
</script>
