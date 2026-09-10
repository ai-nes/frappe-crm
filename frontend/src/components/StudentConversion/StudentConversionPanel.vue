<template>
  <section class="border-b p-1 sm:p-3" aria-label="Student conversion">
    <Section :label="__('Student conversion')" label-class="px-2 font-semibold" header-class="h-8">
      <div class="space-y-3 px-3 pb-3 text-sm">
        <p v-if="loading" class="text-ink-gray-5" role="status">{{ __('Loading conversion state…') }}</p>
        <template v-else-if="state.converted">
          <p class="text-ink-gray-6">{{ __('This Student case remains intact and is linked to an identity-level Contact.') }}</p>
          <Button v-if="state.contact" size="sm" :label="__('Open Contact')" @click="openContact" />
        </template>
        <template v-else-if="state.advertised">
          <p class="text-ink-gray-6">{{ __('Conversion preserves this Student case and creates or reuses an identity-level Contact.') }}</p>
          <p v-if="errorMessage" class="text-red-600" role="alert">{{ errorMessage }}</p>
          <Button size="sm" variant="solid" :label="errorState?.retryable ? __('Retry conversion') : __('Convert to Contact')" :loading="saving" :disabled="saving || state.revision === null" @click="showConfirmation = true" />
        </template>
        <p v-else class="text-ink-gray-5">{{ __('Conversion is unavailable for the current server state.') }}</p>
      </div>
    </Section>
  </section>

  <Dialog v-model="showConfirmation" :options="{ title: __('Convert to Contact') }" @close="closeConfirmation">
    <template #body-content>
      <div class="space-y-3">
        <p class="text-sm text-ink-gray-7">{{ __('This keeps the Student case and all of its history intact. The resulting Contact represents the resolved identity and may retain other case history.') }}</p>
        <p v-if="errorMessage" class="text-sm text-red-600" role="alert">{{ errorMessage }}</p>
      </div>
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" :disabled="saving" @click="showConfirmation = false" />
        <Button variant="solid" :label="__('Convert to Contact')" :loading="saving" :disabled="saving" @click="submit" />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import Section from '@/components/Section.vue'
import {
  buildStudentConversionPayload,
  conversionErrorState,
  conversionResult,
  createStudentConversionCommandId,
  studentConversionApi,
  studentConversionState,
} from '@/utils/studentConversion'
import { Button, Dialog, call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  student: { type: String, required: true },
  context: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['refresh-required', 'converted'])
const router = useRouter()
const showConfirmation = ref(false)
const saving = ref(false)
const commandId = ref(createStudentConversionCommandId())
const errorState = ref(null)
const state = computed(() => studentConversionState(props.context || {}))
const errorMessage = computed(() => errorState.value?.message || '')

watch(() => props.student, () => {
  commandId.value = createStudentConversionCommandId()
  errorState.value = null
})

function closeConfirmation() {
  if (!saving.value) showConfirmation.value = false
}

function openContact() {
  router.push({ name: 'CRM Contact', params: { crmContactId: state.value.contact } })
}

async function submit() {
  if (saving.value || !state.value.advertised || state.value.revision === null) return
  saving.value = true
  errorState.value = null
  try {
    const result = conversionResult(await call(studentConversionApi.convert, buildStudentConversionPayload({
      student: props.student,
      lifecycleRevision: state.value.revision,
      idempotencyKey: commandId.value,
      correlationId: commandId.value,
    })))
    if (!result.contact) throw new Error(__('The conversion response did not include a Contact.'))
    toast.success(result.replayed ? __('Conversion already completed.') : __('Converted to CRM Contact.'))
    showConfirmation.value = false
    emit('converted', result)
    router.push({ name: 'CRM Contact', params: { crmContactId: result.contact } })
  } catch (error) {
    errorState.value = conversionErrorState(error)
    if (errorState.value.reload) emit('refresh-required')
  } finally {
    saving.value = false
  }
}
</script>
