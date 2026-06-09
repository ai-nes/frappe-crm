<template>
  <div class="flex h-full flex-col gap-4 p-6 text-ink-gray-8">
    <div class="flex justify-between px-2 pt-2">
      <div class="flex flex-col gap-1">
        <h2 class="flex gap-2 text-xl font-semibold leading-none h-5">
          {{ __('Reference Data') }}
        </h2>
        <p class="text-p-base text-ink-gray-6">
          {{ __('Manage provinces, wards, majors, and campuses') }}
        </p>
      </div>
      <div class="flex items-center space-x-2">
        <Button :label="__('Add')" icon-left="plus" variant="solid" @click="addRecord()" />
      </div>
    </div>

    <!-- Sub-tabs -->
    <div class="flex border-b gap-6 px-2">
      <button
        v-for="tab in subTabs"
        :key="tab.doctype"
        class="pb-2 text-base border-b-2 transition-colors"
        :class="
          activeIdx === tab.idx
            ? 'border-ink-gray-9 text-ink-gray-9 font-medium'
            : 'border-transparent text-ink-gray-5 hover:text-ink-gray-8'
        "
        @click="activeIdx = tab.idx"
      >
        {{ __(tab.label) }}
      </button>
    </div>

    <!-- Records list -->
    <div class="flex-1 overflow-y-auto px-2">
      <div v-if="activeResource.loading" class="flex items-center justify-center h-32">
        <LoadingIndicator class="size-6" />
      </div>
      <div v-else-if="activeResource.data?.length" class="flex flex-col divide-y">
        <div
          v-for="record in activeResource.data"
          :key="record.name"
          class="flex items-center justify-between py-3"
        >
          <span class="text-base text-ink-gray-9">{{ record.name }}</span>
          <div class="flex items-center gap-2">
            <Button variant="ghost" icon="edit-2" @click="editRecord(record.name)" />
            <Button
              variant="ghost"
              theme="red"
              icon="trash-2"
              @click="deleteRecord(record.name)"
            />
          </div>
        </div>
      </div>
      <div v-else class="flex flex-col items-center justify-center h-32 text-ink-gray-5">
        {{ __('No records found') }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { createResource, LoadingIndicator, toast } from 'frappe-ui'
import { useDoctypeModal } from '@/composables/doctypeModal'

const { showModal } = useDoctypeModal()

const subTabs = [
  { idx: 0, label: __('Province/City'), doctype: 'CRM Province' },
  { idx: 1, label: __('Ward/Commune'), doctype: 'CRM Ward' },
  { idx: 2, label: __('Major'), doctype: 'CRM Major' },
  { idx: 3, label: __('Campus'), doctype: 'CRM Campus' },
]

const activeIdx = ref(0)
const activeTab = computed(() => subTabs[activeIdx.value])

function makeListResource(doctype) {
  return createResource({
    url: 'frappe.client.get_list',
    params: { doctype, fields: ['name'], limit_page_length: 200 },
    auto: true,
  })
}

const resources = subTabs.map((tab) => makeListResource(tab.doctype))
const activeResource = computed(() => resources[activeIdx.value])

function addRecord() {
  showModal({
    doctype: activeTab.value.doctype,
    title: activeTab.value.label,
    callbacks: {
      afterInsert: () => activeResource.value.reload(),
    },
  })
}

function editRecord(name) {
  showModal({
    doctype: activeTab.value.doctype,
    name,
    title: activeTab.value.label,
    callbacks: {
      afterUpdate: () => activeResource.value.reload(),
    },
  })
}

const deleteResource = createResource({ url: 'frappe.client.delete' })

function deleteRecord(name) {
  deleteResource.submit(
    { doctype: activeTab.value.doctype, name },
    {
      onSuccess: () => {
        toast.success(__('Record deleted'))
        activeResource.value.reload()
      },
      onError: (err) => {
        toast.error(err.messages?.[0] || __('Failed to delete'))
      },
    },
  )
}
</script>
