<template>
  <LayoutHeader>
    <template #left-header>
      <ViewBreadcrumbs routeName="CTV Sale Tasks" />
    </template>
    <template #right-header>
      <Button
        :label="__('Làm mới')"
        iconLeft="refresh-cw"
        :loading="loading"
        @click="reload"
      />
    </template>
  </LayoutHeader>

  <main class="h-full overflow-y-auto bg-surface-gray-1 p-4 sm:p-6">
    <div class="mx-auto max-w-[1440px]">
      <header class="mb-6 flex flex-wrap items-end justify-between gap-6">
        <div>
          <p class="text-sm font-medium text-ink-orange-3">{{ __('Vận hành tuyển sinh') }}</p>
          <h1 class="mt-2 text-2xl font-semibold tracking-tight text-ink-gray-9">
            {{ __('Quản lý task') }}
          </h1>
          <p class="mt-2 max-w-2xl text-sm text-ink-gray-6">
            {{ __('Theo dõi và phân công công việc từ nhiều hồ sơ trong một danh sách tập trung.') }}
          </p>
        </div>
        <div class="min-w-32 rounded-lg border border-outline-gray-2 bg-surface-white px-5 py-3 text-right">
          <p class="text-xs text-ink-gray-5">{{ __('Tổng số task') }}</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-ink-gray-9">{{ formattedTotal }}</p>
        </div>
      </header>

      <section class="overflow-hidden rounded-xl border border-outline-gray-2 bg-surface-white">
        <div class="border-b border-outline-gray-2 p-4 sm:p-5">
          <div class="flex flex-wrap items-center gap-3">
            <div class="relative min-w-64 flex-1 sm:max-w-md">
              <FeatherIcon
                name="search"
                class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-gray-5"
              />
              <Input
                v-model="filters.search"
                :placeholder="__('Tìm task, học sinh, người phụ trách...')"
                class="pl-9"
                aria-label="Tìm task, học sinh, người phụ trách"
              />
            </div>
            <FormControl
              v-model="filters.sortBy"
              type="select"
              :options="sortOptions"
              :label="__('Sắp xếp')"
              class="w-48"
            />
            <span class="ml-auto whitespace-nowrap text-sm text-ink-gray-6">
              <span class="font-semibold tabular-nums text-ink-gray-9">{{ formattedTotal }}</span>
              {{ __('task') }}
            </span>
          </div>

          <div class="mt-4 flex items-center gap-1 overflow-x-auto" role="tablist" :aria-label="__('Lọc theo thời hạn')">
            <button
              v-for="tab in dateTabs"
              :key="tab.value"
              type="button"
              role="tab"
              :aria-selected="filters.dateFilter === tab.value"
              class="min-h-11 whitespace-nowrap rounded-md px-3 text-sm font-medium transition-colors duration-150 hover:bg-surface-gray-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
              :class="filters.dateFilter === tab.value ? 'bg-surface-gray-2 text-ink-gray-9' : 'text-ink-gray-6'"
              @click="filters.dateFilter = tab.value"
            >
              {{ tab.label }}
            </button>
          </div>

          <div class="mt-4 grid gap-3 md:grid-cols-3">
            <FormControl
              v-model="filters.status"
              type="select"
              :options="statusOptions"
              :label="__('Trạng thái')"
            />
            <FormControl
              v-model="filters.priority"
              type="select"
              :options="priorityOptions"
              :label="__('Ưu tiên')"
            />
            <FormControl
              v-model="filters.taskType"
              type="select"
              :options="taskTypeOptions"
              :label="__('Loại task')"
            />
          </div>
        </div>

        <div v-if="loading && !tasks.length" class="p-5" role="status">
          <div class="space-y-3" aria-hidden="true">
            <div v-for="row in 5" :key="row" class="h-16 animate-pulse rounded-md bg-surface-gray-1" />
          </div>
          <span class="sr-only">{{ __('Đang tải task...') }}</span>
        </div>

        <div v-else-if="errorMessage" class="p-8 text-center" role="alert">
          <p class="font-medium text-ink-gray-9">{{ __('Không thể tải danh sách task') }}</p>
          <p class="mt-1 text-sm text-ink-gray-6">{{ errorMessage }}</p>
          <Button class="mt-4" :label="__('Thử lại')" @click="reload" />
        </div>

        <div v-else-if="tasks.length" class="overflow-x-auto">
          <table class="w-full min-w-[980px] text-sm">
            <thead class="bg-surface-gray-1 text-left text-xs font-medium text-ink-gray-6">
              <tr>
                <th class="px-5 py-3">{{ __('Task') }}</th>
                <th class="px-5 py-3">{{ __('Hồ sơ') }}</th>
                <th class="px-5 py-3">{{ __('Người phụ trách') }}</th>
                <th class="px-5 py-3">{{ __('Trạng thái') }}</th>
                <th class="px-5 py-3">{{ __('Ưu tiên') }}</th>
                <th class="px-5 py-3">{{ __('Hạn xử lý') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="task in tasks"
                :key="task.task_id || `${task.doctype}:${task.name}`"
                class="border-t border-outline-gray-1 transition-colors duration-150 hover:bg-surface-gray-1/60"
              >
                <td class="max-w-[340px] px-5 py-3.5">
                  <p class="truncate font-medium text-ink-gray-9">{{ task.title || __('Task chưa có tiêu đề') }}</p>
                  <p class="mt-1 truncate text-xs text-ink-gray-5">{{ taskTypeLabel(task) }}</p>
                </td>
                <td class="px-5 py-3.5">
                  <RouterLink
                    v-if="recordRoute(task)"
                    :to="recordRoute(task)"
                    class="font-medium text-ink-blue-3 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
                  >
                    {{ task.student_name || task.student || task.reference_docname }}
                  </RouterLink>
                  <span v-else class="text-ink-gray-5">{{ __('Chưa liên kết') }}</span>
                </td>
                <td class="px-5 py-3.5 text-ink-gray-7">
                  {{ task.assigned_to_name || task.assigned_to || __('Chưa phân công') }}
                </td>
                <td class="px-5 py-3.5">
                  <span class="inline-flex rounded-md px-2 py-1 text-xs font-medium" :class="statusClasses(task)">
                    {{ statusLabel(task.status) }}
                  </span>
                </td>
                <td class="px-5 py-3.5">
                  <span class="inline-flex items-center gap-1.5 text-xs font-medium" :class="priorityClasses(task.priority)">
                    <span class="size-1.5 rounded-full bg-current" aria-hidden="true" />
                    {{ priorityLabel(task.priority) }}
                  </span>
                </td>
                <td class="px-5 py-3.5">
                  <p :class="task.is_overdue ? 'font-medium text-ink-red-3' : 'text-ink-gray-7'">
                    {{ dueDateLabel(task) }}
                  </p>
                  <p v-if="task.is_overdue" class="mt-1 text-xs text-ink-red-3">{{ __('Quá hạn') }}</p>
                  <p v-else-if="task.is_today" class="mt-1 text-xs text-ink-orange-3">{{ __('Hôm nay') }}</p>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-else class="px-6 py-20 text-center">
          <p class="font-medium text-ink-gray-9">{{ __('Không tìm thấy task phù hợp') }}</p>
          <p class="mt-2 text-sm text-ink-gray-6">{{ __('Thử thay đổi từ khóa hoặc bộ lọc để xem thêm task.') }}</p>
        </div>

        <div v-if="tasks.length" class="flex items-center justify-between border-t border-outline-gray-2 bg-surface-gray-1/40 px-5 py-3">
          <p class="text-xs text-ink-gray-5">
            {{ __('Đang hiển thị') }} {{ tasks.length }} / {{ formattedTotal }} {{ __('task') }}
          </p>
          <Button
            v-if="hasMore"
            variant="subtle"
            :label="__('Tải thêm')"
            :loading="loading"
            @click="loadMore"
          />
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import ViewBreadcrumbs from '@/components/ViewBreadcrumbs.vue'
import { buildSalesTasksParams, normalizeSalesTasksResponse, SALES_TASKS_METHOD } from '@/data/salesTasks'
import { formatDate } from '@/utils'
import { Button, FeatherIcon, FormControl, Input, call } from 'frappe-ui'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'

const filters = reactive({
  search: '',
  dateFilter: 'all',
  status: '',
  priority: '',
  taskType: '',
  sortBy: 'due_date_asc',
})

const dateTabs = [
  { label: __('Tất cả task'), value: 'all' },
  { label: __('Hôm nay'), value: 'today' },
  { label: __('Quá hạn'), value: 'overdue' },
  { label: __('Sắp tới'), value: 'upcoming' },
]

const sortOptions = [
  { label: __('Hạn xử lý gần nhất'), value: 'due_date_asc' },
  { label: __('Cập nhật gần nhất'), value: 'modified_desc' },
  { label: __('Tạo mới gần nhất'), value: 'created_desc' },
]

const statusOptions = [
  { label: __('Tất cả trạng thái'), value: '' },
  { label: __('Đang mở'), value: 'open' },
  { label: __('Đã hoàn thành'), value: 'completed' },
  { label: __('Đã hủy'), value: 'cancelled' },
]

const priorityOptions = [
  { label: __('Tất cả ưu tiên'), value: '' },
  { label: __('Cao'), value: 'High' },
  { label: __('Trung bình'), value: 'Medium' },
  { label: __('Thấp'), value: 'Low' },
]

const taskTypeOptions = [
  { label: __('Tất cả loại task'), value: '' },
  { label: __('Task thủ công'), value: 'Task' },
  { label: __('Liên hệ'), value: 'CONTACT' },
  { label: __('Thông tin'), value: 'INFORMATION' },
  { label: __('Tương tác'), value: 'ENGAGEMENT' },
  { label: __('Chuyển đổi'), value: 'CONVERSION' },
]

const tasks = ref([])
const total = ref(0)
const hasMore = ref(false)
const loading = ref(false)
const errorMessage = ref('')
let requestVersion = 0

const formattedTotal = computed(() => new Intl.NumberFormat('vi-VN').format(total.value))

async function fetchTasks(append = false) {
  const version = ++requestVersion
  const start = append ? tasks.value.length : 0
  if (!append) {
    tasks.value = []
    total.value = 0
    hasMore.value = false
  }
  loading.value = true
  errorMessage.value = ''

  try {
    const response = normalizeSalesTasksResponse(
      await call(SALES_TASKS_METHOD, buildSalesTasksParams(filters, start)),
    )
    if (version !== requestVersion) return

    const nextTasks = append
      ? [...new Map([...tasks.value, ...response.tasks].map((task) => [task.task_id, task])).values()]
      : response.tasks
    tasks.value = nextTasks
    total.value = response.total
    hasMore.value = response.hasMore
  } catch (error) {
    if (version === requestVersion) {
      errorMessage.value = error?.message || __('Không thể tải dữ liệu task.')
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function reload() {
  fetchTasks()
}

function loadMore() {
  if (!loading.value && hasMore.value) fetchTasks(true)
}

const debouncedSearch = useDebounceFn(reload, 350)
watch(() => filters.search, debouncedSearch)
watch(
  () => [filters.dateFilter, filters.status, filters.priority, filters.taskType, filters.sortBy],
  reload,
)

function taskTypeLabel(task) {
  return task.task_type || task.action_type || task.doctype || __('Task')
}

function statusLabel(status) {
  return {
    Backlog: __('Chờ xử lý'),
    Todo: __('Cần làm'),
    'In Progress': __('Đang thực hiện'),
    pending: __('Chờ xử lý'),
    accepted: __('Đã nhận'),
    'in-progress': __('Đang thực hiện'),
    'requires-review': __('Cần kiểm tra'),
    deferred: __('Tạm hoãn'),
    Done: __('Đã hoàn thành'),
    completed: __('Đã hoàn thành'),
    Canceled: __('Đã hủy'),
    cancelled: __('Đã hủy'),
  }[status] || status || __('Chưa xác định')
}

function statusClasses(task) {
  if (['Done', 'completed'].includes(task.status)) return 'bg-green-50 text-green-700'
  if (['Canceled', 'cancelled', 'rejected'].includes(task.status)) return 'bg-surface-gray-2 text-ink-gray-6'
  if (task.is_overdue) return 'bg-red-50 text-red-700'
  return 'bg-blue-50 text-blue-700'
}

function priorityLabel(priority) {
  return { High: __('Cao'), Medium: __('Trung bình'), Low: __('Thấp') }[priority] || priority || __('Chưa đặt')
}

function priorityClasses(priority) {
  return {
    High: 'text-ink-red-3',
    Medium: 'text-ink-orange-3',
    Low: 'text-ink-gray-6',
  }[priority] || 'text-ink-gray-5'
}

function dueDateLabel(task) {
  return task.due_date ? formatDate(task.due_date, 'DD/MM/YYYY HH:mm') : __('Chưa đặt')
}

function recordRoute(task) {
  if (task.student) return { name: 'CRM Student', params: { crmStudentId: task.student } }
  if (task.reference_doctype === 'CRM Student' && task.reference_docname) {
    return { name: 'CRM Student', params: { crmStudentId: task.reference_docname } }
  }
  if (task.reference_doctype === 'CRM Contact' && task.reference_docname) {
    return { name: 'CRM Contact', params: { crmContactId: task.reference_docname } }
  }
  return null
}

onMounted(reload)
onBeforeUnmount(() => {
  requestVersion += 1
})
</script>
