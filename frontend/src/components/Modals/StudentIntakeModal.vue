<template>
  <Dialog v-model="show" :options="{ title: __('Tạo Lead'), size: 'xl' }">
    <template #body-content>
      <p class="mb-4 text-sm text-ink-gray-6">
        {{ __('Nhập thông tin Lead. Cần ít nhất một số điện thoại hoặc địa chỉ email hợp lệ.') }}
      </p>
      <div
        class="mb-4 rounded border border-outline-gray-2 bg-surface-gray-1 p-3 text-sm text-ink-gray-6"
        role="status"
      >
        {{ assignmentMessage }}
        <p v-if="isServerManagedCampus" class="mt-1">
          {{ __('Campus được tự động lấy theo hồ sơ nhân viên của bạn.') }}
        </p>
      </div>
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
          :label="__('Hủy')"
          :disabled="loading"
          @click="show = false"
        />
        <Button
          variant="solid"
          :label="__('Tạo')"
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
import { usersStore } from '@/stores/users'
import { call, toast } from 'frappe-ui'
import { computed, reactive, ref } from 'vue'
import {
  buildIntakePayload,
  createCommandId,
  intakeAssignmentExpectation,
  intakeResultKind,
  isServerManagedIntakeProfile,
  safeCommandError,
} from '@/utils/studentOwnership'

const emit = defineEmits(['completed', 'review-required'])
const show = defineModel({ type: Boolean })
const { getCurrentUser } = usersStore()
const currentProfile = computed(() => getCurrentUser()?.crm_profile)
const isServerManagedCampus = computed(() =>
  isServerManagedIntakeProfile(currentProfile.value),
)

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
})

const fieldLayoutContext = reactive({
  fieldPropertyOverrides: {},
  fieldHtmlMap: {},
})

const tabs = computed(() => [
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
                label: 'Họ và tên',
                reqd: 1,
              },
              {
                fieldname: 'phone',
                fieldtype: 'Data',
                label: 'Điện thoại',
                options: 'Phone',
                description: phoneError.value,
                description_is_error: Boolean(phoneError.value),
              },
              {
                fieldname: 'email',
                fieldtype: 'Data',
                label: 'Email',
                options: 'Email',
                description: emailError.value,
                description_is_error: Boolean(emailError.value),
              },
              {
                fieldname: 'province',
                fieldtype: 'Link',
                label: 'Tỉnh/Thành phố',
                options: 'CRM Province',
                no_create: isServerManagedIntakeProfile(currentProfile.value),
              },
              {
                fieldname: 'ward',
                fieldtype: 'Link',
                label: 'Phường/Xã',
                options: 'CRM Ward',
                no_create: isServerManagedIntakeProfile(currentProfile.value),
              },
              {
                fieldname: 'high_school',
                fieldtype: 'Link',
                label: 'Trường THPT',
                options: 'CRM High School',
                no_create: isServerManagedIntakeProfile(currentProfile.value),
              },
            ],
          },
          {
            name: 'student-information-right',
            fields: [
              {
                fieldname: 'enrollment_status',
                fieldtype: 'Link',
                label: 'Trạng thái tuyển sinh',
                options: 'CRM Term',
                link_filters: JSON.stringify({ category: 'enrollment_status', is_active: 1 }),
                no_create: isServerManagedIntakeProfile(currentProfile.value),
              },
              {
                fieldname: 'source',
                fieldtype: 'Link',
                label: 'Nguồn',
                options: 'CRM Lead Source',
                no_create: isServerManagedIntakeProfile(currentProfile.value),
              },
              {
                fieldname: 'branch',
                fieldtype: 'Link',
                label: 'Campus',
                options: 'CRM Campus',
                reqd: 1,
                read_only: isServerManagedCampus.value,
                no_create: isServerManagedIntakeProfile(currentProfile.value),
              },
              {
                fieldname: 'major',
                fieldtype: 'Link',
                label: 'Ngành quan tâm',
                options: 'CRM Major',
                no_create: isServerManagedIntakeProfile(currentProfile.value),
              },
              {
                fieldname: 'admission_year',
                fieldtype: 'Link',
                label: 'Năm tuyển sinh',
                options: 'CRM Admission Year',
                reqd: 1,
                no_create: isServerManagedIntakeProfile(currentProfile.value),
              },
              {
                fieldname: 'aspiration',
                fieldtype: 'Link',
                label: 'Nguyện vọng',
                options: 'CRM Term',
                link_filters: JSON.stringify({
                  category: 'aspiration',
                  is_active: 1,
                  term_name: ['in', ['NV1', 'NV2', 'NV3']],
                }),
                no_create: isServerManagedIntakeProfile(currentProfile.value),
              },
            ],
          },
        ],
      },
      {
        name: 'phase3-intake-controls',
        label: __('Giấy tờ tùy thân'),
        collapsible: true,
        opened: false,
        columns: [
          {
            name: 'phase3-intake-left',
            fields: [
              {
                fieldname: 'id_number',
                fieldtype: 'Data',
                label: 'Số định danh (không bắt buộc)',
              },
            ],
          },
        ],
      },
    ],
  },
])

const idempotencyKey = ref(createCommandId())
const identifiers = reactive({
  source_record_id: createCommandId(),
})
const loading = ref(false)
const error = ref('')
const result = ref(null)

const assignmentExpectation = computed(() =>
  intakeAssignmentExpectation(currentProfile.value),
)

const assignmentMessage = computed(() => {
  if (assignmentExpectation.value.kind === 'self')
    return __('Lead sẽ tự động được giao cho bạn.')
  if (assignmentExpectation.value.kind === 'team')
    return __('Lead sẽ tự động được đưa vào nhóm của bạn.')
  return __('Việc phân công sẽ được xác định tự động theo quyền truy cập của bạn.')
})

const phoneError = computed(() => {
  const value = form.phone.trim()
  if (!value) return ''
  return /^[+]?\d[\d\s().-]{7,19}$/.test(value)
    ? ''
    : __('Số điện thoại không hợp lệ.')
})

const emailError = computed(() => {
  const value = form.email.trim()
  if (!value) return ''
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
    ? ''
    : __('Địa chỉ email không hợp lệ.')
})

const isValid = computed(() =>
  Boolean(
    form.student_name.trim() &&
    form.admission_year &&
    (isServerManagedCampus.value || form.branch) &&
    (form.phone.trim() || form.email.trim()) &&
    !phoneError.value &&
    !emailError.value,
  ),
)

const resultMessage = computed(() => {
  const messages = {
    attached: __('Lead đã được gắn vào hồ sơ tuyển sinh hiện có.'),
    created: __('Đã tạo Lead.'),
    review_required: __('Cần duyệt trước khi tiếp tục Lead này.'),
  }
  return messages[intakeResultKind(result.value)] || __('Đã hoàn tất.')
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
    if (kind === 'review_required') {
      show.value = false
      emit('review-required', response)
    } else {
      emit('completed', response)
    }
    toast.success(resultMessage.value)
    idempotencyKey.value = createCommandId()
  } catch (err) {
    console.error('[StudentIntake] submit/validation error', {
      error: err,
      form: {
        student_name: form.student_name,
        has_phone: Boolean(form.phone.trim()),
        has_email: Boolean(form.email.trim()),
        enrollment_status: form.enrollment_status,
        admission_year: form.admission_year,
        branch: form.branch,
      },
    })
    error.value = safeCommandError(err, __('Unable to submit intake.'))
  } finally {
    loading.value = false
  }
}
</script>
