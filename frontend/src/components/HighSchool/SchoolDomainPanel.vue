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
      <section aria-labelledby="school360-overview-heading" class="rounded-lg border p-4">
        <div class="mb-2 flex items-center justify-between gap-2">
          <h3 id="school360-overview-heading" class="text-base font-semibold text-ink-gray-9">
            {{ __('School 360 overview') }}
          </h3>
          <span class="text-xs text-ink-gray-5">{{ overviewState }}</span>
        </div>
        <div v-if="overview.error" class="flex items-center justify-between rounded-lg border border-outline-red-2 bg-surface-red-1 p-3 text-sm" role="alert">
          <span>{{ __('Unable to load scoped School 360 evidence.') }}</span>
          <Button :label="__('Retry')" variant="ghost" @click="overview.reload()" />
        </div>
        <div v-else class="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <div class="text-xs text-ink-gray-5">{{ __('Identity') }}</div>
            <div class="font-medium text-ink-gray-9">{{ overviewSection('identity')?.school_name || __('Unavailable') }}</div>
            <div class="text-ink-gray-6">{{ geographyLabel }}</div>
          </div>
          <div>
            <div class="text-xs text-ink-gray-5">{{ __('Intelligence') }}</div>
            <div class="font-medium text-ink-gray-9">{{ intelligenceLabel }}</div>
            <div class="text-xs text-ink-gray-5">{{ sectionState('intelligence') }}</div>
          </div>
          <div>
            <div class="text-xs text-ink-gray-5">{{ __('Latest outcome') }}</div>
            <div class="font-medium text-ink-gray-9">{{ outcomesLabel }}</div>
            <div class="text-xs text-ink-gray-5">{{ sectionStatusLabel('outcomes') }}</div>
          </div>
        </div>
      </section>
      <section aria-labelledby="annual-snapshots-heading">
        <div class="mb-2 flex items-center justify-between gap-2">
          <h3 id="annual-snapshots-heading" class="text-base font-semibold text-ink-gray-9">
            {{ __('Annual Snapshots') }}
          </h3>
          <span class="text-xs text-ink-gray-5">{{ sectionStatusLabel('academic_scale') }}</span>
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
                <th scope="col" class="px-3 py-2">{{ __('NE Actual') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('Average Score') }}</th>
                <th scope="col" class="px-3 py-2">{{ __('Verification') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in snapshots.data || []" :key="row.name" class="border-b last:border-0">
                <td class="px-3 py-2">{{ row.admission_year }}</td>
                <td class="px-3 py-2">{{ displayNumber(row.ne_actual) }}</td>
                <td class="px-3 py-2">{{ displayNumber(row.average_score) }}</td>
                <td class="px-3 py-2">{{ row.verification_status || __('Review Required') }}</td>
              </tr>
              <tr v-if="!(snapshots.data || []).length">
                <td colspan="4" class="px-3 py-4 text-center text-ink-gray-5">{{ snapshotEmptyLabel }}</td>
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
          <span class="text-xs text-ink-gray-5">{{ sectionStatusLabel('stakeholders') }}</span>
          <a :href="listUrl('CRM School Stakeholder')" class="text-sm text-ink-blue-7 hover:underline focus-visible:outline focus-visible:outline-2">
            {{ __('View list') }}
          </a>
        </div>
        <div v-if="people.error" class="mb-2 flex items-center justify-between rounded-lg border border-outline-red-2 bg-surface-red-1 p-3 text-sm" role="alert">
          <span>{{ __('Unable to load stakeholders.') }}</span>
          <Button :label="__('Retry')" variant="ghost" @click="overview.reload()" />
        </div>
        <div class="grid gap-2 md:grid-cols-2">
          <div
            v-for="(person, personIndex) in people.data || []"
            :key="`${person.full_name || person.stakeholder_role || 'stakeholder'}-${personIndex}`"
            class="rounded-lg border p-3"
          >
            <div class="font-medium text-ink-gray-9">{{ person.full_name || __('Stakeholder identity unavailable') }}</div>
            <div class="text-sm text-ink-gray-6">{{ person.stakeholder_role || person.position_title || __('Stakeholder') }}</div>
            <div class="mt-1 text-xs text-ink-gray-5">{{ person.relationship_status || __('No relationship status') }}</div>
          </div>
          <div v-if="!(people.data || []).length" class="rounded-lg border p-4 text-sm text-ink-gray-5">
            {{ peopleEmptyLabel }}
          </div>
        </div>
      </section>

      <section aria-labelledby="school-activities-heading">
        <div class="mb-2 flex items-center justify-between gap-2">
          <h3 id="school-activities-heading" class="text-base font-semibold text-ink-gray-9">
            {{ __('School Activities') }}
          </h3>
          <span class="text-xs text-ink-gray-5">{{ sectionStatusLabel('activity_history') }}</span>
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
              </tr>
            </thead>
            <tbody>
              <tr v-for="activity in activities.data || []" :key="activity.name" class="border-b last:border-0">
                <td class="px-3 py-2">{{ activity.activity_date }}</td>
                <td class="px-3 py-2">{{ activity.activity_type }}</td>
                <td class="px-3 py-2">{{ activity.status }}</td>
              </tr>
              <tr v-if="!(activities.data || []).length">
                <td colspan="3" class="px-3 py-4 text-center text-ink-gray-5">{{ activityEmptyLabel }}</td>
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

const listResource = (doctype, fields, limit = 50, extraFilters = {}) =>
  createResource({
    url: 'frappe.client.get_list',
    params: {
      doctype,
      fields,
      filters: { high_school: props.highSchoolId, ...extraFilters },
      order_by:
        doctype === 'CRM High School Annual Snapshot'
          ? 'admission_year desc'
          : 'modified desc',
      limit_page_length: limit,
    },
    auto: true,
  })

const overview = createResource({
  url: 'crm.api.school_domain.get_school360_overview',
  params: { high_school: props.highSchoolId },
  auto: true,
})

const snapshots = listResource(
  'CRM High School Annual Snapshot',
  ['name', 'admission_year', 'ne_actual', 'average_score', 'verification_status'],
  5,
  { period_type: 'Annual', verification_status: 'Verified' },
)
const people = computed(() => ({
  data: overview.data?.stakeholders?.data || [],
  loading: overview.loading,
  error: overview.error,
  reload: overview.reload,
}))
const activities = listResource(
  'CRM School Activity',
  ['name', 'activity_date', 'activity_type', 'status'],
)

const loading = computed(() => overview.loading || snapshots.loading || activities.loading)
const summary = computed(() => [
  { label: __('Annual Snapshots'), value: countLabel(snapshots, 5) },
  { label: __('Stakeholders'), value: countLabel(people.value, 50) },
  { label: __('School Activities'), value: countLabel(activities, 50) },
  { label: __('School 360'), value: overviewState.value },
])

const overviewState = computed(() => overview.data?.freshness || (overview.error ? __('Unavailable') : __('Loading')))
const overviewSection = (name) => overview.data?.[name]?.data
const sectionState = (name) => overview.data?.[name]?.status || __('Unavailable')
const geographyLabel = computed(() => {
  const data = overviewSection('geography')
  return data ? [data.province, data.ward].filter(Boolean).join(' · ') || __('Location unavailable') : __('Location unavailable')
})
const intelligenceLabel = computed(() => overviewSection('intelligence')?.potential?.value || __('Unavailable'))
const outcomesLabel = computed(() => displayNumber(overviewSection('outcomes')?.average_score))
const sectionStatusLabel = (section) => {
  const value = overview.data?.[section]
  if (!value) return __('Unavailable')
  const labels = [value.status, value.freshness]
  if (value.verification && value.verification !== 'verified') labels.push(value.verification)
  return labels.filter(Boolean).join(' · ')
}
function evidenceEmptyLabel(section, fallback) {
  const state = sectionState(section)
  const freshness = overview.data?.[section]?.freshness
  if (state === 'denied') return __('Evidence is outside your scope')
  if (state === 'unavailable') return __('Evidence is temporarily unavailable')
  if (state === 'partial' && freshness === 'stale') return __('Partial, stale evidence — review required')
  if (state === 'partial') return __('Partial evidence only — no complete profile is implied')
  if (freshness === 'stale') return __('Evidence is stale and requires review')
  return fallback
}
const snapshotEmptyLabel = computed(() => evidenceEmptyLabel('academic_scale', __('No verified annual snapshots')))
const activityEmptyLabel = computed(() => evidenceEmptyLabel('activity_history', __('No school activities')))
const peopleEmptyLabel = computed(() => evidenceEmptyLabel('stakeholders', __('No stakeholders recorded')))

function countLabel(resource, limit) {
  if (resource.loading || resource.error) return '—'
  return resource.data?.length >= limit ? `${limit}+` : resource.data?.length || 0
}

function listUrl(doctype) {
  return `/app/${doctype.toLowerCase().replaceAll(' ', '-') }?high_school=${encodeURIComponent(props.highSchoolId)}`
}

function displayNumber(value) {
  return value === null || value === undefined || value === '' ? '—' : value
}
</script>
