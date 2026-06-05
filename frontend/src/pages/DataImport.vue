<template>
  <DataImport
    :doctype="route.params.doctype"
    :importName="route.params.importName"
    :doctypeMap="doctypeMap"
  />
</template>

<script setup>
import { usePageMeta } from 'frappe-ui'
import { DataImport } from 'frappe-ui/frappe'
import { useRoute } from 'vue-router'

const route = useRoute()

const doctypeMap = {
  'Enrollment Student': {
    title: 'Enrollment Students',
    listRoute: '/crm/enrollment-students',
    pageRoute: `/crm/enrollment-students/docname`,
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
  Person: {
    title: 'Persons',
    listRoute: '/crm/persons',
    pageRoute: `/crm/persons/docname`,
  },
  Campaign: {
    title: 'Campaigns',
    listRoute: '/crm/campaigns',
    pageRoute: `/crm/campaigns/docname`,
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
