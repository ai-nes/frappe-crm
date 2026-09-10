<template>
  <div class="flex flex-col gap-4">
    <div
      v-for="(group, groupIndex) in groups"
      :key="groupIndex"
      class="rounded-lg border p-3"
    >
      <div class="mb-2 flex items-center justify-between">
        <div class="text-sm font-medium text-ink-gray-6">
          <span v-if="groupIndex === 0">{{ __('Match contacts who are in ANY of these groups:') }}</span>
          <span v-else class="text-ink-gray-5">{{ __('OR') }}</span>
        </div>
        <Button
          variant="ghost"
          icon="trash-2"
          :tooltip="__('Remove group')"
          @click="removeGroup(groupIndex)"
        />
      </div>
      <div class="flex flex-col gap-2">
        <div
          v-for="(condition, conditionIndex) in group.conditions"
          :key="conditionIndex"
          class="flex items-center gap-2"
        >
          <div class="w-40 shrink-0">
            <Select
              :model-value="condition.field"
              :options="fieldOptions"
              :placeholder="__('Field')"
              @change="(e) => setConditionField(group, condition, e.target.value)"
            />
          </div>
          <div class="w-32 shrink-0">
            <Select
              :model-value="condition.operator"
              :options="operatorOptions(condition.field)"
              :placeholder="__('Operator')"
              @change="(e) => (condition.operator = e.target.value)"
            />
          </div>
          <div class="min-w-48 flex-1">
            <QuickFilterField
              v-if="condition.field"
              :filter="valueFilterFor(condition)"
              @applyQuickFilter="(f, v) => (condition.value = v)"
            />
          </div>
          <Button
            variant="ghost"
            icon="x"
            :tooltip="__('Remove condition')"
            @click="removeCondition(group, conditionIndex)"
          />
        </div>
      </div>
      <Button
        class="mt-2"
        variant="ghost"
        iconLeft="plus"
        :label="__('Add condition (AND)')"
        @click="addCondition(group)"
      />
    </div>
    <Button
      variant="outline"
      iconLeft="plus"
      :label="__('Add group (OR)')"
      @click="addGroup"
    />
  </div>
</template>
<script setup>
import QuickFilterField from '@/components/QuickFilterField.vue'
import { Button, Select, createResource } from 'frappe-ui'
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
})
const emit = defineEmits(['update:modelValue'])

const groups = computed(() => props.modelValue?.groups || [])

const fieldsResource = createResource({
  url: 'crm.api.segment.get_segment_fields',
  cache: 'segment-condition-fields',
  auto: true,
})

const fieldOptions = computed(() => {
  if (!fieldsResource.data) return []
  return fieldsResource.data.map((f) => ({ label: f.label, value: f.fieldname }))
})

function getFieldMeta(fieldname) {
  return fieldsResource.data?.find((f) => f.fieldname === fieldname)
}

// QuickFilterField only ever emits a single scalar value, so "in"/"not in"
// (which the backend requires a non-empty list for) are left out here even
// though crm.api.segment.OPERATORS_BY_FIELDTYPE allows them — there's no
// multi-select value control yet to complete those conditions with.
const OPERATORS_BY_FIELDTYPE = {
  Select: ['=', '!='],
  Link: ['=', '!='],
  Check: ['=', '!='],
}

function operatorOptions(fieldname) {
  let meta = getFieldMeta(fieldname)
  let ops = meta ? OPERATORS_BY_FIELDTYPE[meta.fieldtype] || [] : []
  return ops.map((op) => ({ label: op, value: op }))
}

function valueFilterFor(condition) {
  let meta = getFieldMeta(condition.field) || {}
  let options = meta.options
  if (meta.fieldtype === 'Select' && typeof options === 'string') {
    options = options
      .split('\n')
      .filter(Boolean)
      .map((o) => ({ label: o, value: o }))
  }
  return {
    fieldname: condition.field,
    label: meta.label || condition.field,
    fieldtype: meta.fieldtype,
    options,
    value: condition.value,
  }
}

function setConditionField(group, condition, fieldname) {
  condition.field = fieldname
  let meta = getFieldMeta(fieldname)
  condition.operator = meta ? OPERATORS_BY_FIELDTYPE[meta.fieldtype]?.[0] : ''
  condition.value = ''
}

function update(newGroups) {
  emit('update:modelValue', { groups: newGroups })
}

function addGroup() {
  update([...groups.value, { logic: 'AND', conditions: [{ field: '', operator: '', value: '' }] }])
}

function removeGroup(groupIndex) {
  update(groups.value.filter((_, i) => i !== groupIndex))
}

function addCondition(group) {
  group.conditions.push({ field: '', operator: '', value: '' })
  update(groups.value)
}

function removeCondition(group, conditionIndex) {
  group.conditions = group.conditions.filter((_, i) => i !== conditionIndex)
  update(groups.value)
}
</script>
