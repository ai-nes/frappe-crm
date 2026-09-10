<template>
  <Dialog v-model="show" :options="{ title: __('Attach Segment to Campaign'), size: 'lg' }">
    <template #body-content>
      <div class="flex flex-col gap-4">
        <FormControl
          :label="__('Segment')"
        >
          <template #control>
            <Link
              :value="segmentName"
              doctype="CRM Segment"
              :placeholder="__('Select a segment')"
              @change="(value) => (segmentName = value)"
            />
          </template>
        </FormControl>

        <div v-if="preview.loading" class="text-p-sm text-ink-gray-5">
          {{ __('Calculating matches...') }}
        </div>
        <div v-else-if="preview.data" class="text-p-base text-ink-gray-6">
          {{ __('{0} contacts currently match this segment', [preview.data.total]) }}
        </div>

        <ErrorMessage :message="errorMessage" />

        <div v-if="result" class="rounded-lg border p-3 text-p-sm">
          <div>{{ __('Total matches: {0}', [result.total_matches]) }}</div>
          <div>{{ __('Touchpoints created: {0}', [result.created]) }}</div>
          <div>{{ __('Already attached from this segment: {0}', [result.skipped_same_segment]) }}</div>
          <div>{{ __('Skipped (already touched by another source): {0}', [result.skipped_other_source]) }}</div>
          <div v-if="result.failed" class="text-ink-red-4">
            {{ __('Some rows failed to attach — check Error Log for details.') }}
          </div>
        </div>
      </div>
    </template>
    <template #actions>
      <Button
        variant="solid"
        :label="__('Attach')"
        :loading="attaching"
        :disabled="!segmentName"
        @click="attach"
      />
    </template>
  </Dialog>
</template>
<script setup>
import Link from '@/components/Controls/Link.vue'
import {
  Button,
  Dialog,
  ErrorMessage,
  FormControl,
  call,
  createResource,
  toast,
} from 'frappe-ui'
import { ref, watch } from 'vue'

const props = defineProps({
  campaign: { type: String, required: true },
})
const emit = defineEmits(['attached'])

const show = defineModel({ type: Boolean })

const segmentName = ref('')
const errorMessage = ref('')
const attaching = ref(false)
const result = ref(null)

const preview = createResource({
  url: 'crm.api.segment.preview_segment',
  makeParams: () => ({ segment: segmentName.value, page_length: 1 }),
})

watch(segmentName, (value) => {
  result.value = null
  errorMessage.value = ''
  if (value) preview.submit()
})

watch(show, (value) => {
  if (!value) {
    segmentName.value = ''
    result.value = null
    errorMessage.value = ''
  }
})

async function attach() {
  errorMessage.value = ''
  attaching.value = true
  try {
    result.value = await call('crm.api.segment.attach_segment_to_campaign', {
      segment: segmentName.value,
      campaign: props.campaign,
    })
    toast.success(__('Segment attached'))
    emit('attached', result.value)
  } catch (error) {
    errorMessage.value = error?.messages?.[0] || error?.message || __('Failed to attach segment')
  } finally {
    attaching.value = false
  }
}
</script>
