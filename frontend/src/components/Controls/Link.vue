<template>
  <div class="space-y-1.5 p-[2px] -m-[2px]">
    <label v-if="attrs.label" class="block" :class="labelClasses">
      {{ __(attrs.label) }}
    </label>
    <Autocomplete
      ref="autocomplete"
      v-model="value"
      :options="mergedOptions"
      :size="attrs.size || 'sm'"
      :variant="attrs.variant"
      :placeholder="attrs.placeholder"
      :disabled="attrs.disabled"
      :placement="attrs.placement"
      :filterable="false"
    >
      <template #target="{ open, togglePopover }">
        <slot name="target" v-bind="{ open, togglePopover }" />
      </template>

      <template #prefix>
        <slot name="prefix" />
      </template>

      <template #item-prefix="{ active, selected, option }">
        <slot name="item-prefix" v-bind="{ active, selected, option }" />
      </template>

      <template #item-label="{ active, selected, option }">
        <slot name="item-label" v-bind="{ active, selected, option }">
          <div v-if="option.description" class="flex flex-col gap-1">
            <div class="flex-1 font-semibold truncate text-ink-gray-7">
              {{ option.label }}
            </div>
            <div class="flex-1 text-sm truncate text-ink-gray-5">
              {{ option.description }}
            </div>
          </div>
          <div v-else class="flex-1 truncate text-ink-gray-7">
            {{ option.label }}
          </div>
        </slot>
      </template>

      <template #footer="{ value: v, close }">
        <div v-if="attrs.onCreate">
          <Button
            variant="ghost"
            class="w-full !justify-start"
            :label="__('Create New')"
            iconLeft="plus"
            @click="() => attrs.onCreate(v, close)"
          />
        </div>
        <div>
          <Button
            variant="ghost"
            class="w-full !justify-start"
            :label="__('Clear')"
            iconLeft="x"
            @click="() => clearValue(close)"
          />
        </div>
      </template>
    </Autocomplete>
  </div>
</template>

<script setup>
import Autocomplete from '@/components/frappe-ui/Autocomplete.vue'
import { isTranslatable } from '@/utils'
import { watchDebounced } from '@vueuse/core'
import { createResource } from 'frappe-ui'
import { useAttrs, computed, ref, watch } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  filters: { type: [Array, Object, String], default: () => [] },
  modelValue: { type: String, default: '' },
  hideMe: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

const attrs = useAttrs()

const valuePropPassed = computed(() => 'value' in attrs)

const currentValue = computed(() =>
  valuePropPassed.value ? attrs.value : props.modelValue,
)

const value = computed({
  get: () => {
    let v = currentValue.value
    if (isTranslatable(props.doctype)) return __(v)
    return v
  },
  set: (val) => {
    return (
      val?.value &&
      emit(valuePropPassed.value ? 'change' : 'update:modelValue', val?.value)
    )
  },
})

const autocomplete = ref(null)
const text = ref('')

watchDebounced(
  () => autocomplete.value?.query,
  (val) => {
    val = val || ''
    if (text.value === val) return
    text.value = val
    reload(val)
  },
  { debounce: 300, immediate: true },
)

watchDebounced(
  () => props.doctype,
  () => reload(''),
  { debounce: 300, immediate: true },
)

watchDebounced(
  () => props.filters,
  () => {
    reload('', true)
  },
  { debounce: 300, immediate: true },
)

function transformOptions(data) {
  return data.map((option) => {
    // Frappe search_link may not return a `label` field (or label === value/code).
    // When that happens, extract the human-readable name from the first segment
    // of `description` (e.g. "Hà Nội, 01" → "Hà Nội").
    let label = option.label
    if ((!label || label === option.value) && option.description) {
      label = option.description.split(',')[0].trim()
    }
    return {
      label: label || option.value,
      value: option.value,
      description: option.description,
    }
  })
}

const options = createResource({
  url: 'frappe.desk.search.search_link',
  cache: [props.doctype, text.value, props.hideMe, props.filters],
  method: 'POST',
  params: {
    txt: text.value,
    doctype: props.doctype,
    filters: props.filters,
  },
  transform: (data) => {
    let allData = transformOptions(data)
    if (!props.hideMe && props.doctype == 'User') {
      allData.unshift({
        label: '@me',
        value: '@me',
      })
    }
    return allData
  },
})

// When the field has a pre-selected value that may not appear in the initial
// lazy-loaded options (e.g. province code "04" not in the first alphabetical
// page), fetch that specific option so displayValue() can show the proper name.
const selectedOptionResource = createResource({
  url: 'frappe.desk.search.search_link',
  method: 'POST',
  transform: transformOptions,
})

watch(
  currentValue,
  (val) => {
    if (!val || !props.doctype) return
    selectedOptionResource.update({
      params: { txt: val, doctype: props.doctype, filters: props.filters },
    })
    selectedOptionResource.reload()
  },
  { immediate: true },
)

// Merge the pre-fetched selected option into the main options list so that
// Autocomplete's displayValue() can find it and show the human-readable name.
const mergedOptions = computed(() => {
  const main = options.data || []
  const val = currentValue.value
  if (!val) return main
  if (main.find((o) => o.value === val)) return main
  const preloaded = selectedOptionResource.data?.find((o) => o.value === val)
  if (preloaded) return [preloaded, ...main]
  return main
})

function reload(val, force = false) {
  if (!props.doctype) return
  if (
    !force &&
    options.data?.length &&
    val === options.params?.txt &&
    props.doctype === options.params?.doctype
  )
    return

  options.update({
    params: {
      txt: val,
      doctype: props.doctype,
      filters: props.filters,
    },
  })
  options.reload()
}

function clearValue(close) {
  emit(valuePropPassed.value ? 'change' : 'update:modelValue', '')
  close()
}

const labelClasses = computed(() => {
  return [
    {
      sm: 'text-xs',
      md: 'text-base',
    }[attrs.size || 'sm'],
    'text-ink-gray-5',
  ]
})

defineExpose({ reload })
</script>
