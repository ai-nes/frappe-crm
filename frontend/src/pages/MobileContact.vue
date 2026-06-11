<template>
  <LayoutHeader v-if="contact.doc">
    <header
      class="relative flex h-10.5 items-center justify-between gap-2 py-2.5 pl-2"
    >
      <Breadcrumbs :items="breadcrumbs">
        <template #prefix="{ item }">
          <Icon v-if="item.icon" :icon="item.icon" class="mr-2 h-4" />
        </template>
      </Breadcrumbs>
    </header>
  </LayoutHeader>
  <div v-if="contact.doc" class="flex flex-col h-full overflow-hidden">
    <FileUploader
      :validateFile="validateIsImageFile"
      @success="changeContactImage"
    >
      <template #default="{ openFileSelector, error }">
        <div class="flex flex-col items-start justify-start gap-4 p-4">
          <div class="flex gap-4 items-center">
            <div class="group relative h-14.5 w-14.5">
              <Avatar
                size="3xl"
                class="h-14.5 w-14.5"
                :label="contact.doc.full_name"
                :image="contact.doc.image"
              />
              <component
                :is="contact.doc.image ? Dropdown : 'div'"
                v-bind="
                  contact.doc.image
                    ? {
                        options: [
                          {
                            icon: 'upload',
                            label: contact.doc.image
                              ? __('Change Image')
                              : __('Upload Image'),
                            onClick: openFileSelector,
                          },
                          {
                            icon: 'trash-2',
                            label: __('Remove Image'),
                            onClick: () => changeContactImage(''),
                          },
                        ],
                      }
                    : { onClick: openFileSelector }
                "
                class="!absolute bottom-0 left-0 right-0"
              >
                <div
                  class="z-1 absolute bottom-0 left-0 right-0 flex h-14 cursor-pointer items-center justify-center rounded-b-full bg-black bg-opacity-40 pt-5 opacity-0 duration-300 ease-in-out group-hover:opacity-100"
                  style="
                    -webkit-clip-path: inset(22px 0 0 0);
                    clip-path: inset(22px 0 0 0);
                  "
                >
                  <CameraIcon class="h-6 w-6 cursor-pointer text-white" />
                </div>
              </component>
            </div>
            <div class="flex flex-col gap-2 truncate">
              <div class="truncate text-lg font-medium text-ink-gray-9">
                <span v-if="contact.doc.salutation">
                  {{ contact.doc.salutation + '. ' }}
                </span>
                <span>{{ contact.doc.full_name }}</span>
              </div>
              <div class="flex items-center gap-1.5">
                <Button
                  v-if="callEnabled && contact.doc.mobile_no"
                  :label="__('Make a Call')"
                  size="sm"
                  :iconLeft="PhoneIcon"
                  @click="callEnabled && makeCall(contact.doc.mobile_no)"
                />
                <Button
                  v-if="canDelete"
                  :label="__('Delete')"
                  theme="red"
                  size="sm"
                  icon-left="trash-2"
                  @click="deleteContact"
                />
                <span
                  v-if="contact.doc.company_name"
                  class="truncate text-base text-ink-gray-6"
                >
                  {{ contact.doc.company_name }}
                </span>
              </div>
              <ErrorMessage :message="__(error)" />
            </div>
          </div>
        </div>
      </template>
    </FileUploader>
    <div
      v-if="sections.data"
      class="flex flex-1 flex-col justify-between overflow-hidden"
    >
      <SidePanelLayout
        :sections="sections.data"
        doctype="Contact"
        :docname="contact.doc.name"
        @reload="sections.reload"
      />
    </div>
  </div>
</template>

<script setup>
import Icon from '@/components/Icon.vue'
import SidePanelLayout from '@/components/SidePanelLayout.vue'
import LayoutHeader from '@/components/LayoutHeader.vue'
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import CameraIcon from '@/components/Icons/CameraIcon.vue'
import { validateIsImageFile } from '@/utils'
import { getView } from '@/utils/view'
import { useDocument } from '@/data/document'
import { getSettings } from '@/stores/settings'
import { getMeta } from '@/stores/meta'
import { globalStore } from '@/stores/global.js'
import { callEnabled } from '@/composables/telephony'
import {
  Breadcrumbs,
  Avatar,
  FileUploader,
  call,
  createResource,
  usePageMeta,
  Dropdown,
  toast,
} from 'frappe-ui'
import { useDoctypeModal } from '@/composables/doctypeModal'
import { useTelemetry } from 'frappe-ui/frappe'
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const { brand } = getSettings()
const { $dialog, makeCall } = globalStore()

const { doctypeMeta } = getMeta('Contact')
const { capture } = useTelemetry()

const props = defineProps({
  contactId: { type: String, required: true },
})

const route = useRoute()
const router = useRouter()

const {
  document: contact,
  permissions,
  triggerOnRender,
} = useDocument('Contact', props.contactId)

const canDelete = computed(() => permissions.data?.permissions?.delete || false)

onMounted(async () => {
  if (contact.doc) await triggerOnRender()
})

const breadcrumbs = computed(() => {
  let items = [{ label: __('Contacts'), route: { name: 'Contacts' } }]

  if (route.query.view || route.query.viewType) {
    let view = getView(route.query.view, route.query.viewType, 'Contact')
    if (view) {
      items.push({
        label: __(view.label),
        icon: view.icon,
        route: {
          name: 'Contacts',
          params: { viewType: route.query.viewType },
          query: { view: route.query.view },
        },
      })
    }
  }

  items.push({
    label: title.value,
    route: { name: 'Contact', params: { contactId: props.contactId } },
  })
  return items
})

const title = computed(() => {
  let t = doctypeMeta.value?.title_field || 'name'
  return contact.doc?.[t] || props.contactId
})

usePageMeta(() => {
  return {
    title: title.value,
    icon: brand.favicon,
  }
})

function changeContactImage(file) {
  contact.doc.image = file?.file_url || ''
  contact.save.submit(null, {
    onSuccess: () => {
      toast.success(__('Contact Image Updated'))
    },
  })
}

async function deleteContact() {
  $dialog({
    title: __('Delete Contact'),
    message: __('Are you sure you want to delete this contact?'),
    actions: [
      {
        label: __('Delete'),
        theme: 'red',
        variant: 'solid',
        async onClick(close) {
          await call('frappe.client.delete', {
            doctype: 'Contact',
            name: props.contactId,
          })
          close()
          router.push({ name: 'Contacts' })
        },
      },
    ],
  })
}

const sections = createResource({
  url: 'crm.fcrm.doctype.fields_layout.fields_layout.get_sidepanel_sections',
  cache: ['sidePanelSections', 'Contact'],
  params: { doctype: 'Contact' },
  auto: true,
  transform: (data) => computed(() => getParsedSections(data)),
})

function getParsedSections(_sections) {
  return _sections.map((section) => {
    section.columns = section.columns.map((column) => {
      column.fields = column.fields.map((field) => {
        if (field.fieldname === 'email_id') {
          return {
            ...field,
            type: 'dropdown',
            options:
              contact.doc?.email_ids?.map((email) => {
                return {
                  name: email.name,
                  value: email.email_id,
                  selected: email.email_id === contact.doc.email_id,
                  placeholder: 'john@doe.com',
                  onClick: () => {
                    setAsPrimary('email', email.email_id)
                  },
                  onSave: (option, isNew) => {
                    if (isNew) {
                      createNew('email', option.value)
                    } else {
                      editOption(
                        'Contact Email',
                        option.name,
                        'email_id',
                        option.value,
                      )
                    }
                  },
                  onDelete: async (option, isNew) => {
                    contact.doc.email_ids = contact.doc.email_ids.filter(
                      (email) => email.name !== option.name,
                    )
                    if (!isNew) await deleteOption('Contact Email', option.name)
                  },
                }
              }) || [],
            create: () => {
              contact.doc?.email_ids?.push({
                name: 'new-1',
                value: '',
                selected: false,
                isNew: true,
              })
            },
          }
        } else if (field.name === 'mobile_no') {
          return {
            ...field,
            read_only: false,
            fieldtype: 'dropdown',
            options:
              contact.doc?.phone_nos?.map((phone) => {
                return {
                  name: phone.name,
                  value: phone.phone,
                  selected: phone.phone === contact.doc.mobile_no,
                  onClick: () => {
                    setAsPrimary('mobile_no', phone.phone)
                  },
                  onSave: (option, isNew) => {
                    if (isNew) {
                      createNew('phone', option.value)
                    } else {
                      editOption(
                        'Contact Phone',
                        option.name,
                        'phone',
                        option.value,
                      )
                    }
                  },
                  onDelete: async (option, isNew) => {
                    contact.doc.phone_nos = contact.doc.phone_nos.filter(
                      (phone) => phone.name !== option.name,
                    )
                    if (!isNew) await deleteOption('Contact Phone', option.name)
                  },
                }
              }) || [],
            create: () => {
              contact.doc?.phone_nos?.push({
                name: 'new-1',
                value: '',
                selected: false,
                isNew: true,
              })
            },
          }
        } else if (field.name === 'address') {
          return {
            ...field,
            create: (value, close) => {
              showAddressModal()
              close()
            },
            edit: (address) => showAddressModal(address),
          }
        } else {
          return field
        }
      })
      return column
    })
    return section
  })
}

async function setAsPrimary(field, value) {
  let d = await call('crm.api.contact.set_as_primary', {
    contact: contact.doc.name,
    field,
    value,
  })
  if (d) {
    contact.reload()
    toast.success(__('Contact Updated'))
  }
}

async function createNew(field, value) {
  if (!value) return
  let d = await call('crm.api.contact.create_new', {
    contact: contact.doc.name,
    field,
    value,
  })
  if (d) {
    contact.reload()
    toast.success(__('Contact Updated'))
  }
}

async function editOption(doctype, name, fieldname, value) {
  let d = await call('frappe.client.set_value', {
    doctype,
    name,
    fieldname,
    value,
  })
  if (d) {
    contact.reload()
    toast.success(__('Contact Updated'))
  }
}

async function deleteOption(doctype, name) {
  await call('frappe.client.delete', {
    doctype,
    name,
  })
  await contact.reload()
  toast.success(__('Contact Updated'))
}

const { showModal } = useDoctypeModal()

function showAddressModal(_address) {
  showModal({
    name: _address || null,
    doctype: 'Address',
    callbacks: {
      afterInsert: (d) => {
        capture('address_created')
        contact.doc.address = d.name
        contact.save.submit()
      },
    },
  })
}
</script>
