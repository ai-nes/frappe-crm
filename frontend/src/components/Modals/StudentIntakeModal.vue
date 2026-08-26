<template>
  <Dialog v-model="show" :options="{ title: __('Create Student'), size: 'xl' }">
    <template #body-content>
      <p class="mb-4 text-sm text-ink-gray-6">
        {{
          __(
            'Fill in the student information. Provide at least one valid phone number or email address.',
          )
        }}
      </p>
      <FieldLayout
        :tabs="tabs"
        :data="form"
        doctype="CRM Student"
        :context="fieldLayoutContext"
      />
      <ErrorMessage v-if="error" class="mt-4" :message="error" role="alert" />
      <div
        v-if="result"
        class="mt-4 rounded border p-3 text-sm"
        role="status"
        aria-live="polite"
      >
        {{ resultMessage }}
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button
          :label="__('Cancel')"
          :disabled="loading"
          @click="show = false"
        />
        <Button
          variant="solid"
          :label="__('Create')"
          :loading="loading"
          :disabled="!isValid"
          @click="submit"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import FieldLayout from '@/components/FieldLayout/FieldLayout.vue'
import { call, toast } from 'frappe-ui'
import { computed, reactive, ref } from 'vue'
import {
  buildIntakePayload,
  createCommandId,
  intakeResultKind,
  safeCommandError,
} from '@/utils/studentOwnership'

const emit = defineEmits(['completed', 'review-required'])
const show = defineModel({ type: Boolean })

const form = reactive({
  student_name: '',
  enrollment_status: '',
  phone: '',
  source: '',
  email: '',
  branch: '',
  province: '',
  high_school: '',
  ward: '',
  major: '',
  aspiration: '',
  admission_year: '',
  id_number: '',
  owning_team: '',
})

const fieldLayoutContext = reactive({
  fieldPropertyOverrides: {},
  fieldHtmlMap: {},
})

const tabs = [
  {
    name: 'student-intake',
    label: '',
    sections: [
      {
        name: 'student-information',
        label: '',
        hideBorder: true,
        columns: [
          {
            name: 'student-information-left',
            fields: [
              {
                fieldname: 'student_name',
                fieldtype: 'Data',
                label: 'Student Name',
                reqd: 1,
              },
              {
                fieldname: 'phone',
                fieldtype: 'Data',
                label: 'Phone',
                options: 'Phone',
              },
              {
                fieldname: 'email',
                fieldtype: 'Data',
                label: 'Email',
                options: 'Email',
              },
              {
                fieldname: 'province',
                fieldtype: 'Link',
                label: 'Province',
                options: 'CRM Province',
              },
              {
                fieldname: 'ward',
                fieldtype: 'Link',
                label: 'Ward',
                options: 'CRM Ward',
              },
              {
                fieldname: 'aspiration',
                fieldtype: 'Link',
                label: 'Aspiration',
                options: 'CRM Aspiration',
              },
            ],
          },
          {
            name: 'student-information-right',
            fields: [
              {
                fieldname: 'enrollment_status',
                fieldtype: 'Link',
                label: 'Enrollment Status',
                options: 'CRM Enrollment Status',
              },
              {
                fieldname: 'source',
                fieldtype: 'Link',
                label: 'Source',
                options: 'CRM Lead Source',
              },
              {
                fieldname: 'branch',
                fieldtype: 'Link',
                label: 'Campus',
                options: 'CRM Campus',
                reqd: 1,
              },
              {
                fieldname: 'high_school',
                fieldtype: 'Link',
                label: 'High School',
                options: 'CRM High School',
              },
              {
                fieldname: 'major',
                fieldtype: 'Link',
                label: 'Major',
                options: 'CRM Major',
              },
              {
                fieldname: 'admission_year',
                fieldtype: 'Link',
                label: 'Admission Year',
                options: 'CRM Admission Year',
                reqd: 1,
              },
            ],
          },
        ],
      },
      {
        name: 'phase3-intake-controls',
        label: 'Identity and assignment',
        collapsible: true,
        opened: false,
        columns: [
          {
            name: 'phase3-intake-left',
            fields: [
              {
                fieldname: 'id_number',
                fieldtype: 'Data',
                label: 'National ID (optional)',
              },
            ],
          },
          {
            name: 'phase3-intake-right',
            fields: [
              {
                fieldname: 'owning_team',
                fieldtype: 'Link',
                label: 'Initial pool (optional)',
                options: 'CRM Student Pool',
              },
            ],
          },
        ],
      },
    ],
  },
]

const idempotencyKey = ref(createCommandId())
const identifiers = reactive({
  source_record_id: createCommandId(),
})
const loading = ref(false)
const error = ref('')
const result = ref(null)

const isValid = computed(() =>
  Boolean(
    form.student_name.trim() &&
    form.admission_year &&
    form.branch &&
    (form.phone.trim() || form.email.trim()),
  ),
)

const resultMessage = computed(() => {
  const messages = {
    attached: __('Intake attached to the existing admission case.'),
    created: __('Student intake created.'),
    review_required: __(
      'A review is required before this intake can continue.',
    ),
  }
  return messages[intakeResultKind(result.value)] || __('Intake completed.')
})

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const payload = {
      ...buildIntakePayload(form, identifiers),
      idempotency_key: idempotencyKey.value,
      correlation_id: createCommandId(),
    }
    const response = await call('crm.api.student_intake.submit_intake', payload)
    const kind = intakeResultKind(response)
    if (!kind)
      throw new Error(__('The intake service returned an invalid result.'))
    result.value = response
    if (kind === 'review_required') emit('review-required', response)
    else emit('completed', response)
    toast.success(resultMessage.value)
    idempotencyKey.value = createCommandId()
  } catch (err) {
    error.value = safeCommandError(err, __('Unable to submit intake.'))
  } finally {
    loading.value = false
  }
}
</script>
