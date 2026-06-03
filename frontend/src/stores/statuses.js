import { defineStore } from 'pinia'
import { computed } from 'vue'

const COMMUNICATION_STATUSES = [
  { name: 'Open' },
  { name: 'Replied' },
]

export const statusesStore = defineStore('crm-statuses', () => {
  const communicationStatuses = computed(() => ({
    data: COMMUNICATION_STATUSES,
  }))

  function getCommunicationStatus(name) {
    return COMMUNICATION_STATUSES.find((status) => status.name === name)
  }

  return {
    communicationStatuses,
    getCommunicationStatus,
  }
})
