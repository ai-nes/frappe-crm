<template>
  <div class="flex h-full flex-col overflow-y-auto px-5 py-4">
    <div class="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
      <div v-for="item in summary" :key="item.label" class="rounded-lg border p-3">
        <div class="text-xs text-ink-gray-5">{{ item.label }}</div>
        <div class="mt-1 text-xl font-semibold text-ink-gray-9">{{ item.value }}</div>
      </div>
    </div>
    <div v-if="loading" class="py-8 text-center text-ink-gray-5">
      {{ __('Loading school domain data...') }}
    </div>
    <div v-else class="flex flex-col gap-5">
      <section aria-labelledby="annual-snapshots-heading">
        <div class="mb-2 flex items-center justify-between gap-2">
          <h3 id="annual-snapshots-heading" class="text-base font-semibold text-ink-gray-9">
            {{ __('Annual Snapshots') }}
          </h3>
          <a :href="listUrl('CRM High School Annual Snapshot')" class="text-sm text-ink-blue-7 hover:underline focus-visible:outline focus-visible:outline-2">
            {{ __('View list') }}
          </a>
        </div>
        <div v-if="snapshots.error" class="mb-2 flex items-center justify-between rounded-lg border border-outline-red-2 bg-surface-red-1 p-3 text-sm" role="alert">
          <span>{{ __('Unable to load annual snapshots.') }}</span>
          <Button :label="__('Retry')" variant="ghost" @click="snapshots.reload()" />
        </div>
        <div class="overflow-x-auto rounded-lg border">
          <table class="w-full text-left text-sm">
            <caption class="sr-only">{{ __('Annual snapshots for this high school') }}</caption>
            <thead class="border-b bg-surface-gray-1 text-ink-gray-6">
              <tr>
                <th scope="col" class="px-3 py-2">{{ __('Year') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('NE Target') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('NE Actual') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('Key Account') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('Verification') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in snapshots.data || []" :key="row.name" class="border-b last:border-0">
                <td class="px-3 py-2">{{ row.admission_year }}</td>
                <td class="px-3 py-2">{{ displayNumber(row.ne_target) }}</td>
                <td class="px-3 py-2">{{ displayNumber(row.ne_actual) }}</td>
                <td class="px-3 py-2">{{ keyAccountLabel(row) }}</td>
                <td class="px-3 py-2">{{ row.verification_status || __('Review Required') }}</td>
              </tr>
              <tr v-if="!(snapshots.data || []).length">
                <td colspan="5" class="px-3 py-4 text-center text-ink-gray-5">{{ __('No annual snapshots') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="school-people-heading">
        <div class="mb-2 flex items-center justify-between gap-2">
          <h3 id="school-people-heading" class="text-base font-semibold text-ink-gray-9">
            {{ __('People') }}
          </h3>
          <a :href="listUrl('CRM School Stakeholder')" class="text-sm text-ink-blue-7 hover:underline focus-visible:outline focus-visible:outline-2">
            {{ __('View list') }}
          </a>
        </div>
        <div v-if="people.error" class="mb-2 flex items-center justify-between rounded-lg border border-outline-red-2 bg-surface-red-1 p-3 text-sm" role="alert">
          <span>{{ __('Unable to load stakeholders.') }}</span>
          <Button :label="__('Retry')" variant="ghost" @click="people.reload()" />
        </div>
        <div class="grid gap-2 md:grid-cols-2">
          <router-link
            v-for="person in people.data || []"
            :key="person.name"
            :to="{ name: 'CRM Person', params: { crmPersonId: person.person } }"
            class="rounded-lg border p-3 hover:bg-surface-gray-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ink-blue-7"
          >
            <div class="font-medium text-ink-gray-9">{{ person.full_name || person.person }}</div>
            <div class="text-sm text-ink-gray-6">{{ person.stakeholder_role || person.position_title || __('Stakeholder') }}</div>
            <div class="mt-1 text-xs text-ink-gray-5">{{ person.relationship_status || __('No relationship status') }}</div>
          </router-link>
          <div v-if="!(people.data || []).length" class="rounded-lg border p-4 text-sm text-ink-gray-5">
            {{ __('No stakeholders recorded') }}
          </div>
        </div>
      </section>

      <section aria-labelledby="school-activities-heading">
        <div class="mb-2 flex items-center justify-between gap-2">
          <h3 id="school-activities-heading" class="text-base font-semibold text-ink-gray-9">
            {{ __('School Activities') }}
          </h3>
          <a :href="listUrl('CRM School Activity')" class="text-sm text-ink-blue-7 hover:underline focus-visible:outline focus-visible:outline-2">
            {{ __('View list') }}
          </a>
        </div>
        <div v-if="activities.error" class="mb-2 flex items-center justify-between rounded-lg border border-outline-red-2 bg-surface-red-1 p-3 text-sm" role="alert">
          <span>{{ __('Unable to load school activities.') }}</span>
          <Button :label="__('Retry')" variant="ghost" @click="activities.reload()" />
        </div>
        <div class="overflow-x-auto rounded-lg border">
          <table class="w-full text-left text-sm">
            <caption class="sr-only">{{ __('School activities for this high school') }}</caption>
            <thead class="border-b bg-surface-gray-1 text-ink-gray-6">
              <tr>
                <th scope="col" class="px-3 py-2">{{ __('Date') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('Activity') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('Status') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('Owner') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('NE Output') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="activity in activities.data || []" :key="activity.name" class="border-b last:border-0">
                <td class="px-3 py-2">{{ activity.activity_date }}</td>
                <td class="px-3 py-2">{{ activity.activity_type }}</td>
                <td class="px-3 py-2">{{ activity.status }}</td>
                <td class="px-3 py-2">{{ activity.owner_staff || __('Unassigned') }}</td>
                <td class="px-3 py-2">{{ displayNumber(activity.application_count) }}</td>
              </tr>
              <tr v-if="!(activities.data || []).length">
                <td colspan="5" class="px-3 py-4 text-center text-ink-gray-5">{{ __('No school activities') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Button, createResource } from 'frappe-ui'

const props = defineProps({
  highSchoolId: { type: String, required: true },
})

const listResource = (doctype, fields, limit = 50) =>
  createResource({
    url: 'frappe.client.get_list',
    params: {
      doctype,
      fields,
      filters: { high_school: props.highSchoolId },
      order_by:
        doctype === 'CRM High School Annual Snapshot'
          ? 'admission_year desc'
          : 'modified desc',
      limit_page_length: limit,
    },
    auto: true,
  })

const snapshots = listResource(
  'CRM High School Annual Snapshot',
  ['name', 'admission_year', 'ne_target', 'ne_actual', 'key_account_eligible', 'verification_status'],
  5,
)
const people = createResource({
  url: 'crm.api.school_domain.get_school_stakeholders',
  params: { high_school: props.highSchoolId, limit: 50 },
  auto: true,
})
const activities = listResource(
  'CRM School Activity',
  ['name', 'activity_date', 'activity_type', 'status', 'owner_staff', 'application_count'],
)

const loading = computed(() => snapshots.loading || people.loading || activities.loading)
const summary = computed(() => [
  { label: __('Annual Snapshots'), value: countLabel(snapshots, 5) },
  { label: __('Stakeholders'), value: countLabel(people, 50) },
  { label: __('School Activities'), value: countLabel(activities, 50) },
  {
    label: __('Latest Key Account'),
    value: keyAccountLabel(snapshots.data?.[0]),
  },
])

function countLabel(resource, limit) {
  if (resource.loading || resource.error) return '—'
  return resource.data?.length >= limit ? `${limit}+` : resource.data?.length || 0
}

function keyAccountLabel(row) {
  if (!row || row.ne_actual === null || row.ne_actual === undefined || row.ne_actual === '') {
    return __('Review Required')
  }
  return row.key_account_eligible ? __('Eligible') : __('Not Eligible')
}

function listUrl(doctype) {
  return `/app/${doctype.toLowerCase().replaceAll(' ', '-') }?high_school=${encodeURIComponent(props.highSchoolId)}`
}

function displayNumber(value) {
  return value === null || value === undefined || value === '' ? '—' : value
}
</script>
