<template>
  <Dialog v-model="show" :options="{ title: __('Admissions action'), size: 'xl' }" @close="close">
    <template #body-content>
      <form class="space-y-4" @submit.prevent="submit">
        <div>
          <label class="mb-1 block text-sm font-medium text-ink-gray-8" for="admissions-action">
            {{ __('Action') }}
          </label>
          <select
            id="admissions-action"
            v-model="action"
            class="form-select w-full"
            :disabled="saving"
          >
            <option v-for="item in availableActions" :key="item.value" :value="item.value">
              {{ __(item.label) }}
            </option>
          </select>
          <p v-if="selectedAction" class="mt-1 text-sm text-ink-gray-5">
            {{ __(selectedAction.description) }}
          </p>
        </div>

        <FormControl
          v-for="field in fields"
          :key="field.name"
          v-model="payload[field.name]"
          :type="field.type"
          :label="field.label"
          :options="field.options"
          :required="requiredFields.includes(field.name)"
          :disabled="saving"
        />

        <p v-if="displayError" role="alert" class="text-sm text-ink-red-3">{{ displayError }}</p>
        <div class="flex justify-end gap-2 pt-2">
          <Button type="button" :label="__('Cancel')" :disabled="saving" @click="close" />
          <Button type="submit" variant="solid" :label="__('Save action')" :loading="saving" :disabled="saving || !selectedAction" />
        </div>
      </form>
    </template>
  </Dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Button, Dialog, FormControl, call } from 'frappe-ui'
import {
  admissionsActionDefinitions,
  buildAdmissionsActionPayload,
  createAdmissionsCommandId,
  fieldsForAdmissionsAction,
  validateAdmissionsAction,
  studentAdmissionsApi,
} from '@/utils/studentAdmissionsActions'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  student: { type: String, required: true },
  expectedRevision: { type: [Number, String], default: 0 },
  actions: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'success', 'error'])

const show = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const action = ref('digital_signal')
const payload = reactive({})
const saving = ref(false)
const error = ref('')
const idempotencyKey = ref(null)
const availableActions = computed(() => {
  const allowed = new Set(props.actions)
  return admissionsActionDefinitions.filter((item) => allowed.has(item.value))
})
const selectedAction = computed(() => availableActions.value.find((item) => item.value === action.value))
const fields = computed(() =>
  fieldsForAdmissionsAction(action.value).map((field) => ({
    ...field,
    label: __(field.label),
    options: field.options?.map((option) => ({
      ...option,
      label: __(option.label),
    })),
  })),
)
const requiredFields = computed(() => {
  const required = {
    digital_signal: ['signal'],
    call_attempt: ['summary'],
    call_success: ['summary'],
    brochure_sent: ['summary'],
    major_update: ['major'],
    lifecycle_transition: ['to_stage'],
    event_invite: ['event'],
    event_register: ['event'],
    event_checkin: ['event'],
    scholarship_interest: ['target'],
    create_task: ['title'],
    create_insight_note: [],
    assign_counselor: ['counselor'],
  }
  return required[action.value] || []
})
const displayError = computed(() => {
  if (!error.value) return ''
  if (error.value === 'Please provide at least one admissions insight.') return __(error.value)
  const missing = error.value.match(/^Please provide: (.+)\.$/)
  if (missing) {
    const labels = missing[1]
      .split(',')
      .map((name) => fields.value.find((field) => field.name === name.trim())?.label || __(name.trim()))
    return __('Please provide: {0}.', [labels.join(', ')])
  }
  return __(error.value)
})

watch(action, () => {
  Object.keys(payload).forEach((key) => delete payload[key])
  error.value = ''
  idempotencyKey.value = null
})
watch(payload, () => {
  if (!saving.value) idempotencyKey.value = null
}, { deep: true })
watch(availableActions, (next) => {
  if (next.length && !next.some((item) => item.value === action.value)) action.value = next[0].value
}, { immediate: true })

function close() {
  if (!saving.value) show.value = false
}

async function submit() {
  error.value = validateAdmissionsAction(action.value, payload)
  if (error.value) return
  saving.value = true
  try {
    if (!idempotencyKey.value) idempotencyKey.value = createAdmissionsCommandId(action.value)
    const requestPayload = { ...payload }
    if (action.value === 'create_insight_note') {
      requestPayload.content = Object.fromEntries(
        fields.value
          .map((field) => [field.label, String(payload[field.name] || '').trim()])
          .filter(([, value]) => value),
      )
      fields.value.forEach((field) => delete requestPayload[field.name])
    }
    const result = await call(studentAdmissionsApi.perform, buildAdmissionsActionPayload({
      student: props.student,
      action: action.value,
      expectedRevision: props.expectedRevision,
      payload: requestPayload,
      idempotencyKey: idempotencyKey.value,
    }))
    emit('success', result)
    idempotencyKey.value = null
    show.value = false
  } catch (cause) {
    error.value = cause?.messages?.[0] || cause?.message || __('Unable to save this admissions action.')
    emit('error', cause)
  } finally {
    saving.value = false
  }
}
</script>
