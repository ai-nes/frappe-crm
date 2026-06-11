import { ref } from 'vue'

export const showDeleteDocumentModal = ref(false)
export const deleteDocumentModalProps = ref({
  doctype: '',
  docname: '',
  name: '',
})

const LIST_ROUTE_BY_DOCTYPE = {
  Contact: 'Contacts',
  'CRM Contact': 'CRM Contacts',
  'CRM Event': 'CRM Events',
  'CRM Campaign': 'CRM Campaigns',
  'CRM Person': 'CRM Persons',
  'CRM Staff': 'CRM Staff',
  'Task': 'Tasks',
  'CRM Student': 'CRM Students',
  'CRM High School': 'High Schools',
  'Call Log': 'Call Logs',
}

export function openDeleteDocumentModal(doctype, docname, routeName = null) {
  deleteDocumentModalProps.value = {
    doctype,
    docname,
    name: routeName || LIST_ROUTE_BY_DOCTYPE[doctype] || '',
  }
  showDeleteDocumentModal.value = true
}
