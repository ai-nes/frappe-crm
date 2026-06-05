<template>
  <DeleteLinkedDocModal
    v-if="showDeleteDocumentModal"
    v-model="showDeleteDocumentModal"
    v-bind="deleteDocumentModalProps"
  />
</template>

<script setup>
import DeleteLinkedDocModal from '@/components/DeleteLinkedDocModal.vue'
import {
  showDeleteDocumentModal,
  deleteDocumentModalProps,
} from '@/composables/deleteDocumentModal'
</script>
