<template>
  <div
    class="my-3 flex items-center justify-between text-lg font-medium sm:mb-4 sm:mt-8"
  >
    <div class="flex h-8 items-center text-xl font-semibold text-ink-gray-8">
      {{ __('Data') }}
      <Badge
        v-if="document.isDirty"
        class="ml-3"
        :label="__('Not Saved')"
        theme="orange"
      />
    </div>
    <div class="flex gap-1">
      <Button
        v-if="isManager() && !isMobileView"
        :tooltip="__('Edit Fields Layout')"
        :icon="EditIcon"
        @click="showDataFieldsModal = true"
      />
      <Button
        :label="__('Save')"
        :disabled="!document.isDirty || saving"
        variant="solid"
        :loading="saving"
        @click="saveChanges"
      />
    </div>
  </div>
  <div
    v-if="document.get.loading"
    class="flex flex-1 flex-col items-center justify-center gap-3 text-xl font-medium text-ink-gray-6"
  >
    <LoadingIndicator class="h-6 w-6" />
    <span>{{ __('Loading...') }}</span>
  </div>
  <div v-else class="pb-8">
    <FieldLayout
      v-if="tabs.data"
      :tabs="tabs.data"
      :data="document.doc"
      :doctype="doctype"
    />
  </div>
  <DataFieldsModal
    v-if="showDataFieldsModal"
    v-model="showDataFieldsModal"
    :doctype="doctype"
    @reload="
      () => {
        tabs.reload()
        document.reload()
      }
    "
  />
</template>

<script setup>
import EditIcon from '@/components/Icons/EditIcon.vue'
import DataFieldsModal from '@/components/Modals/DataFieldsModal.vue'
import FieldLayout from '@/components/FieldLayout/FieldLayout.vue'
import { Badge, createResource, call, toast } from 'frappe-ui'
import LoadingIndicator from '@/components/Icons/LoadingIndicator.vue'
import { usersStore } from '@/stores/users'
import { useDocument } from '@/data/document'
import { isMobileView } from '@/composables/settings'
import { ref, watch } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
})

const emit = defineEmits(['afterSave'])

const { isManager } = usersStore()

const showDataFieldsModal = ref(false)
const saving = ref(false)

const { document } = useDocument(props.doctype, props.docname)

const tabs = createResource({
  url: 'crm.fcrm.doctype.fields_layout.fields_layout.get_fields_layout',
  cache: ['DataFields', props.doctype],
  params: { doctype: props.doctype, type: 'Data Fields' },
  auto: true,
  transform: (data) => {
    if (props.doctype !== 'CRM Student') return data
    return data.map((tab) => ({
      ...tab,
      sections: tab.sections?.map((section) => ({
        ...section,
        columns: section.columns?.map((col) => ({
          ...col,
          fields: col.fields?.filter((f) => f.fieldname !== 'converted') || [],
        })) || [],
      })) || [],
    }))
  },
})

async function saveChanges() {
  if (!document.isDirty || saving.value) return

  const updatedDoc = { ...document.doc }
  const baseDoc = document.originalDoc ? { ...document.originalDoc } : {}

  const changes = Object.keys(updatedDoc).reduce((acc, key) => {
    if (JSON.stringify(updatedDoc[key]) !== JSON.stringify(baseDoc[key])) {
      acc[key] = updatedDoc[key]
    }
    return acc
  }, {})

  if (!Object.keys(changes).length) return

  saving.value = true
  try {
    await call('frappe.client.set_value', {
      doctype: props.doctype,
      name: props.docname,
      fieldname: changes,
    })
    document.isDirty = false
    await document.reload()
    emit('afterSave', changes)
  } catch (err) {
    toast.error(err.messages?.[0] || err.message || __('An error occurred'))
  } finally {
    saving.value = false
  }
}

watch(
  () => document.doc,
  (newValue, oldValue) => {
    if (!oldValue) return
    if (newValue && oldValue) {
      const isDirty =
        JSON.stringify(newValue) !== JSON.stringify(document.originalDoc)
      document.isDirty = isDirty
      if (isDirty) {
        document.save.loading = false
      }
    }
  },
  { deep: true },
)
</script>
