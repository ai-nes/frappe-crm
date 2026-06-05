<template>
  <LayoutHeader>
    <template #left-header>
      <div class="text-lg font-medium">{{ __('Data Import') }}</div>
    </template>
    <template #right-header>
      <Button
        variant="subtle"
        :label="__('Geography Import')"
        iconLeft="upload"
        @click="router.push({ name: 'GeographyImport' })"
      />
    </template>
  </LayoutHeader>
  <div
    v-if="isDataImportList"
    class="mx-5 mb-4 rounded-lg border border-outline-gray-2 bg-surface-white p-4"
  >
    <div class="flex items-start justify-between gap-4">
      <div class="max-w-3xl">
        <div class="text-base font-medium text-ink-gray-9">
          {{ __('Geography Import') }}
        </div>
        <div class="mt-1 text-sm text-ink-gray-7">
          {{
            __(
              'Import one Excel file with province, ward, high school, address, and region columns. The system will create or update linked geography records automatically.',
            )
          }}
        </div>
      </div>
      <Button
        variant="solid"
        :label="__('Import Geography Excel')"
        iconLeft="upload"
        @click="router.push({ name: 'GeographyImport' })"
      />
    </div>
  </div>
  <DataImport
    :doctype="route.params.doctype"
    :importName="route.params.importName"
    :doctypeMap="doctypeMap"
  />
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import { Button, usePageMeta } from 'frappe-ui'
import { DataImport } from 'frappe-ui/frappe'
import { useRoute, useRouter } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()
const router = useRouter()
const isDataImportList = computed(
  () => !route.params.doctype && !route.params.importName,
)

const doctypeMap = {
  'CRM Student': {
    title: 'CRM Students',
    listRoute: '/crm/crm-students',
    pageRoute: `/crm/crm-students/docname`,
  },
  'CRM Contact': {
    title: 'CRM Contacts',
    listRoute: '/crm/crm-contacts',
    pageRoute: `/crm/crm-contacts/docname`,
  },
  'CRM High School': {
    title: 'High Schools',
    listRoute: '/crm/high-schools',
    pageRoute: `/crm/high-schools/docname`,
  },
  'CRM Person': {
    title: 'CRM Persons',
    listRoute: '/crm/crm-persons',
    pageRoute: `/crm/crm-persons/docname`,
  },
  'CRM Campaign': {
    title: 'CRM Campaigns',
    listRoute: '/crm/crm-campaigns',
    pageRoute: `/crm/crm-campaigns/docname`,
  },
  'CRM Event': {
    title: 'CRM Events',
    listRoute: '/crm/crm-events',
    pageRoute: `/crm/crm-events/docname`,
  },
  Contact: {
    title: 'Contacts',
    listRoute: '/crm/contacts',
    pageRoute: `/crm/contacts/docname`,
  },
  'CRM Task': {
    title: 'Tasks',
    listRoute: '/crm/tasks',
  },
  'CRM Call Log': {
    title: 'Call Log',
    listRoute: '/crm/call-logs',
  },
}

usePageMeta(() => {
  return {
    title: __('Data Import'),
  }
})
</script>
