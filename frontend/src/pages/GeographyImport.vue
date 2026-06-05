<template>
  <LayoutHeader>
    <template #left-header>
      <div class="flex items-center gap-2">
        <Button
          variant="ghost"
          iconLeft="arrow-left"
          @click="router.push({ name: 'DataImportList' })"
        />
        <div class="text-lg font-medium">{{ __('Geography Import') }}</div>
      </div>
    </template>
    <template #right-header>
      <GeographyImportButton variant="solid" @imported="goToHighSchools" />
    </template>
  </LayoutHeader>
  <div class="mx-auto flex max-w-3xl flex-col gap-6 px-5 py-8">
    <div class="rounded-lg border bg-surface-white p-6">
      <div class="mb-2 text-lg font-medium text-ink-gray-9">
        {{ __('Import Geography Excel') }}
      </div>
      <div class="text-base text-ink-gray-7">
        {{
          __(
            'Upload one .xlsx file with province, ward, high school, address, and region columns. The system will create or update linked geography records automatically.',
          )
        }}
      </div>
    </div>
  </div>
</template>

<script setup>
import GeographyImportButton from '@/components/GeographyImportButton.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import { Button, usePageMeta } from 'frappe-ui'
import { useRouter } from 'vue-router'

const router = useRouter()

function goToHighSchools() {
  router.push({ name: 'High Schools', params: { viewType: 'list' } })
}

usePageMeta(() => {
  return {
    title: __('Geography Import'),
  }
})
</script>
