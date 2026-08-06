<template>
  <Dialog v-model="show" :options="{ title: __('AI Draft'), size: '2xl' }">
    <template #body-content>
      <div v-if="state === 'request'" class="flex flex-col gap-4">
        <FormControl
          type="select"
          :label="__('Purpose')"
          v-model="purpose"
          :options="purposeOptions"
        />
        <FormControl
          type="textarea"
          :label="__('Instruction (optional)')"
          v-model="instruction"
          :placeholder="__('Anything specific this email should mention or focus on')"
        />
        <div v-if="error" class="text-sm text-ink-red-3">{{ error }}</div>
        <div class="flex justify-end">
          <Button
            variant="solid"
            :label="__('Generate')"
            :disabled="!purpose"
            @click="generate()"
          />
        </div>
      </div>

      <div v-else class="flex flex-col gap-4">
        <div v-if="loading" class="flex h-40 items-center justify-center">
          <LoadingIndicator class="h-6 w-6 text-ink-gray-4" />
        </div>
        <template v-else>
          <div v-if="error" class="text-sm text-ink-red-3">{{ error }}</div>
          <template v-else>
            <div>
              <div class="mb-1 text-xs text-ink-gray-4">{{ __('SUBJECT') }}</div>
              <div class="text-base text-ink-gray-9">{{ subject }}</div>
            </div>
            <div>
              <div class="mb-1 text-xs text-ink-gray-4">{{ __('BODY') }}</div>
              <div class="whitespace-pre-wrap text-sm text-ink-gray-8">{{ body }}</div>
            </div>
          </template>
        </template>
        <div class="flex justify-between">
          <Button :label="__('Discard')" @click="discard()" />
          <div class="flex gap-2">
            <Button :label="__('Regenerate')" :disabled="loading" @click="regenerate()" />
            <Button
              variant="solid"
              :label="__('Accept')"
              :disabled="loading || !!error"
              @click="accept()"
            />
          </div>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Button, FormControl, LoadingIndicator, call } from 'frappe-ui'
import { ref, watch } from 'vue'

const props = defineProps({
  contact: { type: String, default: '' },
})

const emit = defineEmits(['apply'])

const show = defineModel({ type: Boolean })

const purposeOptions = [
  { label: __('Follow-up after counseling'), value: 'Follow-up after counseling' },
  { label: __('Scholarship information'), value: 'Scholarship information' },
  { label: __('Tuition information'), value: 'Tuition information' },
  { label: __('Application reminder'), value: 'Application reminder' },
  { label: __('Missing document reminder'), value: 'Missing document reminder' },
  { label: __('Event invitation'), value: 'Event invitation' },
  { label: __('Dormitory information'), value: 'Dormitory information' },
  { label: __('Career information'), value: 'Career information' },
  { label: __('Re-engagement'), value: 'Re-engagement' },
  { label: __('Custom'), value: 'Custom' },
]

const state = ref('request') // 'request' | 'result'
const loading = ref(false)
const error = ref('')

const purpose = ref('')
const instruction = ref('')
const draftName = ref('')
const subject = ref('')
const body = ref('')

function reset() {
  state.value = 'request'
  loading.value = false
  error.value = ''
  purpose.value = ''
  instruction.value = ''
  draftName.value = ''
  subject.value = ''
  body.value = ''
}

async function generate() {
  if (!purpose.value) return
  state.value = 'result'
  loading.value = true
  error.value = ''
  try {
    let result = await call('crm.api.ai_email.generate_email_draft', {
      contact: props.contact,
      purpose: purpose.value,
      instruction: instruction.value || undefined,
    })
    draftName.value = result.name
    subject.value = result.subject
    body.value = result.body
  } catch (e) {
    error.value = e.messages?.[0] || e.message || __('Failed to generate draft')
  } finally {
    loading.value = false
  }
}

async function regenerate() {
  let abandoned = draftName.value
  loading.value = true
  error.value = ''
  if (abandoned) {
    try {
      await call('crm.api.ai_email.cancel_draft', { draft: abandoned })
    } catch (e) {
      // best-effort cleanup, still proceed with a fresh generation
    }
  }
  await generate()
}

async function discard() {
  if (draftName.value) {
    try {
      await call('crm.api.ai_email.cancel_draft', { draft: draftName.value })
    } catch (e) {
      // best-effort cleanup on discard
    }
  }
  show.value = false
}

function accept() {
  emit('apply', { subject: subject.value, body: body.value })
  show.value = false
}

watch(show, (value, oldValue) => {
  if (value) {
    reset()
  } else if (oldValue && state.value === 'result' && draftName.value) {
    // Dismissed any other way (e.g. clicking outside) — treat like Discard
    call('crm.api.ai_email.cancel_draft', { draft: draftName.value }).catch(() => {})
  }
})
</script>
