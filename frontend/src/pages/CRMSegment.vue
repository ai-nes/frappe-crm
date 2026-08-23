<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[
          { label: __('Segments'), route: { name: 'CRM Segments' } },
          { label: title || __('New Segment') },
        ]"
      />
    </template>
    <template #right-header>
      <Button
        variant="solid"
        :label="__('Save')"
        :loading="saving"
        @click="save"
      />
    </template>
  </LayoutHeader>
  <div class="flex h-full flex-1 flex-col gap-6 overflow-y-auto p-6">
    <div class="flex items-end gap-4">
      <div class="flex-1">
        <FormControl
          v-model="title"
          type="text"
          :label="__('Title')"
          :placeholder="__('e.g. Hot leads in Hanoi')"
        />
      </div>
      <FormControl
        v-model="isPublic"
        type="checkbox"
        :label="__('Public (visible to everyone)')"
      />
    </div>
    <ErrorMessage :message="errorMessage" />

    <div>
      <h3 class="mb-2 text-base font-medium text-ink-gray-7">
        {{ __('Filter Rules') }}
      </h3>
      <SegmentConditionBuilder v-model="filters" />
    </div>

    <div class="rounded-lg border p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-base font-medium text-ink-gray-7">
          {{ __('Preview') }}
        </h3>
        <Button
          :label="__('Refresh')"
          :loading="preview.loading"
          @click="refreshPreview"
        />
      </div>
      <div v-if="preview.data" class="text-p-base text-ink-gray-6">
        {{ __('{0} matching contacts', [preview.data.total]) }}
      </div>
      <div v-if="preview.data?.contacts?.length" class="mt-2 flex flex-col gap-1">
        <div
          v-for="contact in preview.data.contacts"
          :key="contact.name"
          class="text-p-sm text-ink-gray-6"
        >
          {{ contact.full_name || contact.name }}
          <span class="text-ink-gray-4">({{ contact.phone || contact.email }})</span>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import Breadcrumbs from '@/components/Breadcrumbs.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import SegmentConditionBuilder from '@/components/SegmentConditionBuilder.vue'
import {
  Button,
  ErrorMessage,
  FormControl,
  call,
  createDocumentResource,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  crmSegmentId: { type: String, default: '' },
})

const router = useRouter()
const isNew = computed(() => !props.crmSegmentId || props.crmSegmentId === 'new')

const errorMessage = ref('')
const saving = ref(false)

const title = ref('')
const isPublic = ref(false)
const filters = ref({ groups: [{ logic: 'AND', conditions: [{ field: '', operator: '', value: '' }] }] })

const segment = ref(null)

function onSegmentLoaded(doc) {
  title.value = doc.title
  isPublic.value = Boolean(doc.is_public)
  filters.value = doc.filters || { groups: [] }
}

watch(
  () => props.crmSegmentId,
  () => {
    if (isNew.value) {
      segment.value = null
      title.value = ''
      isPublic.value = false
      filters.value = { groups: [{ logic: 'AND', conditions: [{ field: '', operator: '', value: '' }] }] }
      return
    }
    segment.value = createDocumentResource({
      doctype: 'CRM Segment',
      name: props.crmSegmentId,
      onSuccess: onSegmentLoaded,
    })
    // A cached resource for this id may already hold data (and won't
    // re-fire onSuccess synchronously), so seed the form from it too.
    if (segment.value.doc) onSegmentLoaded(segment.value.doc)
  },
  { immediate: true },
)

async function save() {
  errorMessage.value = ''
  saving.value = true
  try {
    if (isNew.value) {
      let doc = await call('frappe.client.insert', {
        doc: {
          doctype: 'CRM Segment',
          title: title.value,
          is_public: isPublic.value ? 1 : 0,
          filters: filters.value,
        },
      })
      toast.success(__('Segment created'))
      router.replace({ name: 'CRM Segment', params: { crmSegmentId: doc.name } })
    } else {
      segment.value.doc.title = title.value
      segment.value.doc.is_public = isPublic.value ? 1 : 0
      segment.value.doc.filters = filters.value
      await segment.value.save.submit()
      toast.success(__('Segment saved'))
    }
  } catch (error) {
    errorMessage.value = error?.messages?.[0] || error?.message || __('Failed to save segment')
  } finally {
    saving.value = false
  }
}

const preview = createResource({
  url: 'crm.api.segment.preview_segment',
  makeParams() {
    // Always preview the in-memory draft, including unsaved edits to an
    // existing segment — previewing by saved name would silently ignore
    // filter changes made since the last save.
    return { filters: filters.value }
  },
})

function refreshPreview() {
  preview.submit()
}
</script>
