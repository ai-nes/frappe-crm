<template>
  <Dialog
    v-model="show"
    :options="{ title: __('Add Chart') }"
    @close="show = false"
  >
    <template #body-content>
      <div class="flex flex-col gap-4">
        <FormControl
          v-model="chartType"
          type="select"
          :label="__('Chart Type')"
          :options="chartTypes"
        />
        <FormControl
          v-if="chartType === 'number_chart'"
          v-model="numberChart"
          type="select"
          :label="__('Number Chart')"
          :options="numberCharts"
        />
        <FormControl
          v-if="chartType === 'axis_chart'"
          v-model="axisChart"
          type="select"
          :label="__('Axis Chart')"
          :options="axisCharts"
        />
        <FormControl
          v-if="chartType === 'donut_chart'"
          v-model="donutChart"
          type="select"
          :label="__('Donut Chart')"
          :options="donutCharts"
        />
      </div>
    </template>
    <template #actions>
      <div class="flex items-center justify-end gap-2">
        <Button variant="outline" :label="__('Cancel')" @click="show = false" />
        <Button variant="solid" :label="__('Add')" @click="addChart" />
      </div>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { getRandom } from '@/utils'
import { createResource, Dialog, FormControl } from 'frappe-ui'
import { ref, reactive, inject } from 'vue'

const show = defineModel({
  type: Boolean,
  default: false,
})

const items = defineModel('items', {
  type: Array,
  default: () => [],
})

const fromDate = inject('fromDate', ref(''))
const toDate = inject('toDate', ref(''))
const filters = inject('filters', reactive({ period: '', user: '' }))

const chartType = ref('spacer')
const chartTypes = [
  { label: __('Spacer'), value: 'spacer' },
  { label: __('Number Chart'), value: 'number_chart' },
  { label: __('Axis Chart'), value: 'axis_chart' },
  { label: __('Donut Chart'), value: 'donut_chart' },
]

const numberChart = ref('')
const numberCharts = [
  { label: __('Total Students'), value: 'total_students' },
  { label: __('Total Contacts'), value: 'total_contacts' },
  { label: __('Qualified Contacts'), value: 'qualified_contacts' },
  { label: __('Enrolled Contacts'), value: 'enrolled_contacts' },
]

const axisChart = ref('admission_trend')
const axisCharts = [
  { label: __('Admission Trend'), value: 'admission_trend' },
  { label: __('Contacts by High School'), value: 'contacts_by_high_school' },
  { label: __('Contacts by Assignee'), value: 'contacts_by_assignee' },
]

const donutChart = ref('contacts_by_stage')
const donutCharts = [
  { label: __('Contacts by Stage'), value: 'contacts_by_stage' },
  { label: __('Contacts by Source'), value: 'contacts_by_source' },
  { label: __('Students by Source'), value: 'students_by_source' },
]

async function addChart() {
  show.value = false
  if (chartType.value == 'spacer') {
    items.value.push({
      name: 'spacer',
      type: 'spacer',
      layout: { x: 0, y: 0, w: 4, h: 2, i: 'spacer_' + getRandom(4) },
    })
  } else {
    await getChart(chartType.value)
  }
}

async function getChart(type: string) {
  let name =
    type == 'number_chart'
      ? numberChart.value
      : type == 'axis_chart'
        ? axisChart.value
        : donutChart.value

  await createResource({
    url: 'crm.api.dashboard.get_chart',
    params: {
      name,
      type,
      from_date: fromDate.value,
      to_date: toDate.value,
      user: filters.user,
    },
    auto: true,
    onSuccess: (data = {}) => {
      let width = 4
      let height = 2

      if (['axis_chart', 'donut_chart'].includes(type)) {
        width = 10
        height = 7
      }

      items.value.push({
        name,
        type,
        layout: {
          x: 0,
          y: 0,
          w: width,
          h: height,
          i: name + '_' + getRandom(4),
        },
        data: data,
      })
    },
  })
}
</script>
