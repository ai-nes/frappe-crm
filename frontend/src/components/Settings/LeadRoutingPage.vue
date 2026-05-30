<template>
  <div class="flex h-full flex-col gap-4 p-6 text-ink-gray-8">
    <div class="flex justify-between px-2 pt-2">
      <div class="flex flex-col gap-1">
        <h2 class="flex gap-2 text-xl font-semibold leading-none h-5">
          {{ __('Phân phối lead') }}
        </h2>
        <p class="text-p-base text-ink-gray-6">
          {{ __('Cấu hình tự động phân phối lead theo chi nhánh và tỉnh/thành phố') }}
        </p>
      </div>
      <Button
        :label="__('Thêm quy tắc')"
        icon-left="plus"
        variant="solid"
        @click="openAdd"
      />
    </div>

    <div v-if="rulesResource.loading" class="flex items-center justify-center h-32">
      <LoadingIndicator class="size-6" />
    </div>

    <div v-else-if="rulesResource.data?.length" class="overflow-x-auto px-2">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b text-left text-ink-gray-5">
            <th class="pb-2 pr-4 font-medium">{{ __('Chi nhánh') }}</th>
            <th class="pb-2 pr-4 font-medium">{{ __('Tỉnh/TP') }}</th>
            <th class="pb-2 pr-4 font-medium">{{ __('Trường THPT') }}</th>
            <th class="pb-2 pr-4 font-medium">{{ __('Hoạt động') }}</th>
            <th class="pb-2 pr-4 font-medium">{{ __('Nhân viên') }}</th>
            <th class="pb-2 font-medium"></th>
          </tr>
        </thead>
        <tbody class="divide-y">
          <tr
            v-for="rule in rulesResource.data"
            :key="rule.name"
            class="hover:bg-surface-gray-2"
          >
            <td class="py-3 pr-4">{{ rule.branch }}</td>
            <td class="py-3 pr-4">{{ rule.province }}</td>
            <td class="py-3 pr-4 text-ink-gray-5">
              {{ rule.school || __('(tất cả trường)') }}
            </td>
            <td class="py-3 pr-4">
              <span
                class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
                :class="rule.is_active ? 'bg-green-100 text-green-700' : 'bg-surface-gray-3 text-ink-gray-5'"
              >
                {{ rule.is_active ? __('Đang hoạt động') : __('Tạm dừng') }}
              </span>
            </td>
            <td class="py-3 pr-4">{{ rule.staff_count }} {{ __('nhân viên') }}</td>
            <td class="py-3">
              <div class="flex items-center gap-1">
                <Button variant="ghost" icon="edit-2" @click="openEdit(rule.name)" />
                <Button
                  variant="ghost"
                  theme="red"
                  icon="trash-2"
                  @click="deleteRule(rule.name)"
                />
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="mt-3 text-xs text-ink-gray-5 px-1">
        {{ __('Lead thiếu chi nhánh hoặc tỉnh sẽ không được phân phối tự động.') }}
      </p>
    </div>

    <div v-else class="flex flex-col items-center justify-center h-32 text-ink-gray-5">
      {{ __('Chưa có quy tắc phân phối nào') }}
    </div>

    <LeadRoutingModal
      v-model="showModal"
      :rule-name="editingRule"
      @saved="onSaved"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { createResource, LoadingIndicator, toast } from 'frappe-ui'
import LeadRoutingModal from './LeadRoutingModal.vue'

const showModal = ref(false)
const editingRule = ref(null)

const rulesResource = createResource({
  url: 'frappe.client.get_list',
  params: {
    doctype: 'CRM Lead Routing Rule',
    fields: ['name', 'branch', 'province', 'school', 'is_active', 'staff'],
    limit_page_length: 500,
    order_by: 'branch asc, province asc, school asc',
  },
  auto: true,
  transform(data) {
    return data.map((r) => ({
      ...r,
      staff_count: r.staff?.length ?? 0,
    }))
  },
})

function openAdd() {
  editingRule.value = null
  showModal.value = true
}

function openEdit(name) {
  editingRule.value = name
  showModal.value = true
}

const deleteResource = createResource({ url: 'frappe.client.delete' })

function deleteRule(name) {
  if (!confirm(__('Xóa quy tắc phân phối này? Lead từ chi nhánh/tỉnh tương ứng sẽ không được tự động phân phối.'))) return
  deleteResource.submit(
    { doctype: 'CRM Lead Routing Rule', name },
    {
      onSuccess: () => {
        toast.success(__('Đã xóa quy tắc'))
        rulesResource.reload()
      },
      onError: (err) => {
        toast.error(err.messages?.[0] || __('Xóa thất bại'))
      },
    },
  )
}

function onSaved() {
  rulesResource.reload()
}
</script>
