<template>
  <EditValueModal
    v-if="showEditModal"
    v-model="showEditModal"
    :doctype="doctype"
    :selectedValues="selectedValues"
    @reload="reload"
  />
  <AssignmentModal
    v-if="showAssignmentModal"
    v-model="showAssignmentModal"
    v-model:assignees="bulkAssignees"
    :docs="selectedValues"
    :doctype="doctype"
    @reload="reload"
  />
  <AssignStaffModal
    v-if="showAssignStaffModal && isContact"
    v-model="showAssignStaffModal"
    :doctype="doctype"
    :selectedValues="selectedValues"
    @reload="reload"
  />
  <DeleteLinkedDocModal
    v-if="showDeleteDocModal.showLinkedDocsModal"
    v-model="showDeleteDocModal.showLinkedDocsModal"
    :doctype="props.doctype"
    :docname="showDeleteDocModal.docname"
    :reload="reload"
  />
  <BulkDeleteLinkedDocModal
    v-if="showDeleteDocModal.showDeleteModal"
    v-model="showDeleteDocModal.showDeleteModal"
    :doctype="props.doctype"
    :items="showDeleteDocModal.items"
    :reload="reload"
  />
</template>

<script setup>
import EditValueModal from '@/components/Modals/EditValueModal.vue'
import AssignmentModal from '@/components/Modals/AssignmentModal.vue'
import AssignStaffModal from '@/components/Modals/AssignStaffModal.vue'
import { setupListCustomizations } from '@/utils'
import { globalStore } from '@/stores/global'
import { useTelemetry } from 'frappe-ui/frappe'
import { call, toast } from 'frappe-ui'
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  doctype: { type: String, default: '' },
  options: {
    type: Object,
    default: () => ({
      hideEdit: false,
      hideDelete: false,
      hideAssign: false,
    }),
  },
})

const list = defineModel({ type: Object })

const router = useRouter()

const { $dialog, $socket } = globalStore()
const { capture } = useTelemetry()

const showEditModal = ref(false)
const selectedValues = ref([])
const unselectAllAction = ref(() => {})
const showDeleteDocModal = ref({
  showLinkedDocsModal: false,
  showDeleteModal: false,
  docname: null,
})
function editValues(selections, unselectAll) {
  selectedValues.value = selections
  showEditModal.value = true
  unselectAllAction.value = unselectAll
}


function deleteValues(selections, unselectAll) {
  unselectAllAction.value = unselectAll

  const selectedDocs = Array.from(selections)
  if (selectedDocs.length == 1) {
    showDeleteDocModal.value = {
      showLinkedDocsModal: true,
      docname: selectedDocs[0],
    }
  } else {
    showDeleteDocModal.value = {
      showDeleteModal: true,
      items: selectedDocs,
    }
  }
}

const showAssignmentModal = ref(false)
const bulkAssignees = ref([])
const showAssignStaffModal = ref(false)
const canAssignStaff = ref(false)

const isStudent = computed(() => props.doctype === 'CRM Student')
const isContact = computed(() => props.doctype === 'CRM Contact')

function assignValues(selections, unselectAll) {
  showAssignmentModal.value = true
  selectedValues.value = selections
  unselectAllAction.value = unselectAll
}

function assignStaffValues(selections, unselectAll) {
  showAssignStaffModal.value = true
  selectedValues.value = selections
  unselectAllAction.value = unselectAll
}

function clearAssignments(selections, unselectAll) {
  $dialog({
    title: __('Clear Assignment'),
    message: __('Are you sure you want to clear assignment for {0} item(s)?', [
      selections.size,
    ]),
    variant: 'solid',
    theme: 'red',
    actions: [
      {
        label: __('Clear Assignment'),
        variant: 'solid',
        theme: 'red',
        onClick: (close) => {
          capture('bulk_clear_assignment')
          call('frappe.desk.form.assign_to.remove_multiple', {
            doctype: props.doctype,
            names: JSON.stringify(Array.from(selections)),
            ignore_permissions: true,
          }).then(() => {
            toast.success(__('Assignment Cleared Successfully'))
            reload(unselectAll)
            close()
          })
        },
      },
    ],
  })
}

const customBulkActions = ref([])
const customListActions = ref([])

function bulkActions(selections, unselectAll) {
  let actions = []

  // Student ownership is an event command, never a generic bulk field edit.
  if (!props.options.hideEdit && !isStudent.value) {
    actions.push({
      label: __('Edit'),
      onClick: () => editValues(selections, unselectAll),
    })
  }

  if (!props.options.hideDelete) {
    actions.push({
      label: __('Delete'),
      onClick: () => deleteValues(selections, unselectAll),
    })
  }

  if (!props.options.hideAssign && !isStudent.value) {
    actions.push({
      label: __('Assign To'),
      onClick: () => assignValues(selections, unselectAll),
    })
    actions.push({
      label: __('Clear Assignment'),
      onClick: () => clearAssignments(selections, unselectAll),
    })
  }

  if (
    isContact.value &&
    canAssignStaff.value
  ) {
    actions.push({
      label: __('Assign Staff'),
      onClick: () => assignStaffValues(selections, unselectAll),
    })
  }



  customBulkActions.value.forEach((action) => {
    actions.push({
      label: __(action.label),
      onClick: () =>
        action.onClick({
          list: list.value,
          selections,
          unselectAll,
          call,
          createToast: toast.create,
          toast,
          $dialog,
          router,
        }),
    })
  })
  return actions
}

function reload(unselectAll) {
  showDeleteDocModal.value = {
    showLinkedDocsModal: false,
    showDeleteModal: false,
    docname: null,
  }

  unselectAllAction.value?.()
  unselectAll?.()
  list.value?.reload()
}

onMounted(async () => {
  if (isContact.value) {
    canAssignStaff.value = await call('crm.api.staff_assignment.can_assign_staff')
  }
  if (!list.value?.data) return
  let customization = await setupListCustomizations(list.value.data, {
    list: list.value,
    call,
    createToast: toast.create,
    toast,
    $dialog,
    $socket,
    router,
  })
  customBulkActions.value =
    customization?.bulkActions || list.value?.data?.bulkActions || []
  customListActions.value =
    customization?.actions || list.value?.data?.listActions || []
})

defineExpose({
  bulkActions,
  customListActions,
})
</script>
