<template>
  <Dialog
    v-model="show"
    :options="{
      title: isEdit ? __('Chỉnh sửa quy tắc phân phối') : __('Thêm quy tắc phân phối'),
      size: 'xl',
    }"
  >
    <template #body-content>
      <div class="flex flex-col gap-4">
        <div class="grid grid-cols-2 gap-4">
          <FormControl
            type="link"
            :label="__('Chi nhánh')"
            doctype="CRM Branch"
            v-model="form.branch"
            :required="true"
          />
          <FormControl
            type="link"
            :label="__('Tỉnh/Thành phố')"
            doctype="CRM Province"
            v-model="form.province"
            :required="true"
          />
        </div>
        <FormControl
          type="link"
          :label="__('Trường THPT (cụ thể)')"
          doctype="CRM Organization"
          v-model="form.school"
          :placeholder="__('Tất cả trường (fallback)')"
          :description="__('Nếu không chọn, quy tắc áp dụng cho tất cả lead từ tỉnh này')"
        />
        <FormControl
          type="checkbox"
          :label="__('Đang hoạt động')"
          v-model="form.is_active"
        />

        <!-- Staff list -->
        <div class="flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <label class="text-sm font-medium text-ink-gray-7">{{ __('Danh sách nhân viên') }}</label>
            <Button
              size="sm"
              variant="ghost"
              icon="plus"
              :label="__('Thêm nhân viên')"
              @click="addStaff"
            />
          </div>
          <div v-if="form.staff.length" class="flex flex-col gap-2 rounded border p-2">
            <div
              v-for="(row, idx) in form.staff"
              :key="idx"
              class="flex items-center gap-2"
            >
              <div class="flex-1">
                <FormControl
                  type="link"
                  doctype="User"
                  :placeholder="__('Chọn nhân viên')"
                  v-model="row.user"
                />
              </div>
              <Button
                variant="ghost"
                theme="red"
                icon="trash-2"
                @click="removeStaff(idx)"
              />
            </div>
          </div>
          <p v-else class="text-sm text-ink-gray-5">
            {{ __('Chưa có nhân viên — lead sẽ không được phân phối tự động') }}
          </p>
        </div>
      </div>
    </template>
    <template #actions>
      <div class="flex gap-2 justify-end">
        <Button variant="outline" :label="__('Hủy')" @click="show = false" />
        <Button
          variant="solid"
          :label="__('Lưu')"
          :loading="saving"
          @click="save"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { createResource, Dialog, FormControl, toast } from 'frappe-ui'

const props = defineProps({
  modelValue: Boolean,
  ruleName: { type: String, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const show = ref(props.modelValue)
watch(() => props.modelValue, (v) => (show.value = v))
watch(show, (v) => emit('update:modelValue', v))

const isEdit = ref(false)
const saving = ref(false)

const form = ref({
  branch: '',
  province: '',
  school: '',
  is_active: true,
  round_robin_index: 0,
  staff: [],
})

const getDoc = createResource({ url: 'frappe.client.get' })
const saveDoc = createResource({ url: 'frappe.client.save' })
const insertDoc = createResource({ url: 'frappe.client.insert' })

watch(
  () => props.ruleName,
  async (name) => {
    if (!name) {
      isEdit.value = false
      form.value = { branch: '', province: '', school: '', is_active: true, staff: [] }
      return
    }
    isEdit.value = true
    const doc = await getDoc.submit({ doctype: 'CRM Lead Routing Rule', name })
    form.value = {
      branch: doc.branch,
      province: doc.province,
      school: doc.school || '',
      is_active: !!doc.is_active,
      round_robin_index: doc.round_robin_index ?? 0,
      staff: (doc.staff || []).map((s) => ({ user: s.user })),
    }
  },
  { immediate: true },
)

function addStaff() {
  form.value.staff.push({ user: '' })
}

function removeStaff(idx) {
  form.value.staff.splice(idx, 1)
}

async function save() {
  if (!form.value.branch || !form.value.province) {
    toast.error(__('Chi nhánh và Tỉnh/Thành phố là bắt buộc'))
    return
  }
  if (!form.value.staff.filter((s) => s.user).length) {
    toast.error(__('Thêm ít nhất một nhân viên'))
    return
  }
  saving.value = true
  try {
    const docData = {
      doctype: 'CRM Lead Routing Rule',
      branch: form.value.branch,
      province: form.value.province,
      school: form.value.school || '',
      is_active: form.value.is_active ? 1 : 0,
      staff: form.value.staff
        .filter((s) => s.user)
        .map((s) => ({ doctype: 'CRM Lead Routing Staff', user: s.user })),
    }

    if (isEdit.value) {
      await saveDoc.submit({ doc: { ...docData, name: props.ruleName, round_robin_index: form.value.round_robin_index } })
    } else {
      await insertDoc.submit({ doc: docData })
    }

    toast.success(__('Đã lưu quy tắc phân phối'))
    show.value = false
    emit('saved')
  } catch (err) {
    toast.error(err.messages?.[0] || __('Lưu thất bại'))
  } finally {
    saving.value = false
  }
}
</script>
