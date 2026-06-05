<template>
  <div class="flex flex-col items-end gap-1">
    <input
      ref="fileInput"
      type="file"
      accept=".xlsx"
      class="hidden"
      @change="onFileSelected"
    />
    <Button
      :variant="variant"
      :label="
        uploadState.uploading
          ? __('Uploading {0}%', [uploadState.progress])
          : label
      "
      iconLeft="upload"
      :loading="uploadState.uploading || importing"
      @click="openFileSelector"
    />
    <ErrorMessage
      v-if="uploadState.error"
      class="max-w-64"
      :message="__(uploadState.error)"
    />
  </div>
</template>

<script setup>
import { Button, ErrorMessage, FileUploadHandler, call, toast } from 'frappe-ui'
import { ref } from 'vue'

const props = defineProps({
  label: {
    type: String,
    default: () => __('Import Geography Excel'),
  },
  variant: {
    type: String,
    default: 'subtle',
  },
})

const emit = defineEmits(['imported'])

const fileInput = ref(null)
const importing = ref(false)
const uploadState = ref({
  uploading: false,
  progress: 0,
  error: '',
})

function openFileSelector() {
  uploadState.value.error = ''
  fileInput.value?.click()
}

function validateExcelFile(file) {
  let name = file?.name || ''
  if (!/\.xlsx$/i.test(name)) {
    return __('Please upload an Excel file')
  }
}

function resetUploadState() {
  uploadState.value.uploading = false
  uploadState.value.progress = 0
}

async function onFileSelected(event) {
  let file = event?.target?.files?.[0]
  if (!file) return

  let validationError = validateExcelFile(file)
  if (validationError) {
    uploadState.value.error = validationError
    event.target.value = ''
    return
  }

  uploadState.value.error = ''
  let uploader = new FileUploadHandler()
  uploader.on('start', () => {
    uploadState.value.uploading = true
    uploadState.value.progress = 0
  })
  uploader.on('progress', (data) => {
    uploadState.value.progress = Math.floor(
      ((data?.uploaded || 0) / (data?.total || 1)) * 100,
    )
  })
  uploader.on('error', (error) => {
    uploadState.value.error = parseUploadError(error)
    resetUploadState()
  })
  uploader.on('finish', () => {
    resetUploadState()
  })

  try {
    let uploaded = await uploader.upload(file, {
      file,
      fileObj: file,
      private: true,
      folder: 'Home/Attachments',
    })
    await runImport(uploaded)
  } catch (error) {
    uploadState.value.error = parseUploadError(error)
    resetUploadState()
  } finally {
    event.target.value = ''
  }
}

function parseUploadError(error) {
  let errorMessage = 'Error Uploading File'
  if (error?.message) {
    errorMessage = error.message
  } else if (error?._server_messages) {
    errorMessage = JSON.parse(JSON.parse(error._server_messages)[0]).message
  } else if (error?.exc) {
    errorMessage = JSON.parse(error.exc)[0].split('\n').slice(-2, -1)[0]
  }
  return errorMessage
}

async function runImport(file) {
  if (!file?.file_url) return

  importing.value = true
  try {
    let result = await call(
      'crm.api.geography_import.import_geography_high_schools',
      { file_url: file.file_url },
    )
    let errorCount = result.errors?.length || 0
    toast.success(
      __(
        'Imported {0} row(s). Created: {1}. Updated: {2}. Skipped: {3}.',
        [
          result.processed || 0,
          totalCounts(result.created),
          totalCounts(result.updated),
          result.skipped || 0,
        ],
      ),
    )
    if (errorCount) {
      console.warn('Geography import errors', result.errors)
      toast.error(__('Some rows were skipped. Check console for details.'))
    }
    emit('imported', result)
  } finally {
    importing.value = false
  }
}

function totalCounts(counts) {
  return Object.values(counts || {}).reduce((total, count) => total + count, 0)
}
</script>
