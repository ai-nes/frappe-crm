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
  Campaign: 'Campaigns',
  Person: 'Persons',
  Staff: 'Staff',
  'CRM Task': 'Tasks',
  'Enrollment Student': 'Enrollment Students',
  'CRM High School': 'High Schools',
  'CRM Call Log': 'Call Logs',
}

export function openDeleteDocumentModal(doctype, docname, routeName = null) {
  deleteDocumentModalProps.value = {
    doctype,
    docname,
    name: routeName || LIST_ROUTE_BY_DOCTYPE[doctype] || '',
  }
  showDeleteDocumentModal.value = true
}
