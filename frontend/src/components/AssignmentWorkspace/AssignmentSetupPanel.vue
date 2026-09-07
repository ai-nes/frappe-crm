<template>
  <section class="flex flex-col gap-5" data-testid="assignment-setup-panel">
    <div
      v-if="!workflowOnly"
      class="flex flex-wrap items-start justify-between gap-3"
    >
      <div>
        <h2 class="text-lg font-semibold text-ink-gray-9">
          {{ __('Thiết lập') }}
        </h2>
        <p class="mt-1 text-sm text-ink-gray-6">
          {{ __('Khu vực → Nhóm phụ trách → Nhân sự') }}
        </p>
      </div>
      <Button
        variant="subtle"
        size="sm"
        :label="__('Làm mới')"
        iconLeft="refresh-cw"
        :loading="loading"
        @click="$emit('refresh')"
      />
    </div>

    <div
      v-if="!canManage"
      class="rounded-lg border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900"
    >
      {{ __('Chỉ System Manager được thay đổi thiết lập phân bổ.') }}
    </div>

    <div
      v-else-if="error"
      class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900"
      role="alert"
    >
      <p class="font-medium">{{ __('Không thể tải phần thiết lập') }}</p>
      <p class="mt-1">{{ errorMessage(error) }}</p>
      <Button
        class="mt-3"
        size="sm"
        :label="__('Thử lại')"
        :loading="loading"
        @click="$emit('refresh')"
      />
    </div>

    <template v-else>
      <div
        v-if="!workflowOnly"
        class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <div
          v-for="item in summaryCards"
          :key="item.label"
          class="rounded-lg border border-outline-gray-2 bg-surface-white p-4"
        >
          <p class="text-xs text-ink-gray-5">{{ item.label }}</p>
          <p class="mt-2 text-2xl font-semibold text-ink-gray-9">
            {{ item.value }}
          </p>
        </div>
      </div>

      <section
        v-if="workflowOnly"
        class="rounded-lg border border-blue-100 bg-blue-50/50 p-4"
        data-testid="assignment-setup-guide"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 class="font-semibold text-ink-gray-9">
              {{ __('Các bước setup') }}
            </h3>
            <p class="mt-1 text-sm text-ink-gray-6">
              {{ __('Làm theo thứ tự để Lead mới được phân công đúng người.') }}
            </p>
          </div>
          <span class="text-sm font-medium text-blue-700">
            {{ completedSteps }}/{{ workflowSteps.length }}
            {{ __('bước đã xong') }}
          </span>
        </div>
        <div class="mt-4 grid gap-2">
          <button
            v-for="step in workflowSteps"
            :key="step.key"
            type="button"
            class="flex items-start gap-3 rounded-lg border bg-surface-white p-3 text-left transition hover:border-blue-300 hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            :class="step.done ? 'border-green-200' : 'border-outline-gray-2'"
            :data-testid="`assignment-setup-step-${step.key}`"
            @click="openStep(step)"
          >
            <span
              class="flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
              :class="
                step.done
                  ? 'bg-green-100 text-green-700'
                  : 'bg-blue-100 text-blue-700'
              "
            >
              <FeatherIcon
                v-if="step.done"
                name="check"
                class="size-4"
                aria-hidden="true"
              />
              <span v-else>{{ step.number }}</span>
            </span>
            <span class="min-w-0">
              <span class="block font-medium text-ink-gray-9">{{
                step.label
              }}</span>
              <span class="mt-0.5 block text-xs text-ink-gray-6">{{
                step.description
              }}</span>
              <span
                class="mt-2 inline-flex text-xs font-medium"
                :class="step.done ? 'text-green-700' : 'text-blue-700'"
              >
                {{ step.done ? __('Đã xong · Xem lại') : __('Thiết lập ngay') }}
              </span>
            </span>
          </button>
        </div>
      </section>

      <template v-if="!workflowOnly">
        <section
          id="assignment-setup-team"
          class="order-2 rounded-lg border border-outline-gray-2 bg-surface-white"
        >
          <div class="flex items-center justify-between gap-3 p-4">
            <div class="min-w-0">
              <span class="block font-semibold text-ink-gray-9">{{
                __('Nhóm phụ trách')
              }}</span>
              <span class="mt-1 block text-xs text-ink-gray-5">{{
                __('Tạo nhóm và chọn cơ sở hoạt động.')
              }}</span>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <Button
                variant="solid"
                size="sm"
                :label="__('Tạo nhóm')"
                iconLeft="plus"
                @click="openTeam(null)"
              />
              <button
                type="button"
                class="inline-flex min-h-9 min-w-9 items-center justify-center rounded-md text-ink-gray-5 hover:bg-surface-gray-2 focus:outline-none focus:ring-2 focus:ring-outline-gray-4"
                :aria-expanded="sections.team"
                :aria-label="sections.team ? __('Thu gọn nhóm') : __('Mở nhóm')"
                :title="sections.team ? __('Thu gọn nhóm') : __('Mở nhóm')"
                @click="toggleSection('team')"
              >
                <FeatherIcon
                  :name="sections.team ? 'chevron-up' : 'chevron-down'"
                  class="size-4"
                />
              </button>
            </div>
          </div>
          <div v-if="sections.team" class="border-t border-outline-gray-1">
            <div class="overflow-x-auto">
              <table class="w-full min-w-[760px] text-sm">
                <thead
                  class="bg-surface-gray-2 text-left text-xs text-ink-gray-6"
                >
                  <tr>
                    <th class="px-4 py-3">{{ __('Nhóm') }}</th>
                    <th class="px-4 py-3">{{ __('Cơ sở') }}</th>
                    <th class="px-4 py-3">{{ __('Nhân sự') }}</th>
                    <th class="px-4 py-3">{{ __('Khu vực') }}</th>
                    <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
                    <th class="px-4 py-3 text-right">{{ __('Thao tác') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="team in data?.teams || []"
                    :key="team.id"
                    class="border-t border-outline-gray-1 align-top"
                  >
                    <td class="px-4 py-3">
                      <p class="font-medium text-ink-gray-9">
                        {{ team.team_name }}
                      </p>
                      <p class="mt-1 text-xs text-ink-gray-5">
                        {{ team.team_type }}
                      </p>
                    </td>
                    <td class="px-4 py-3 text-ink-gray-7">
                      {{ team.campus_name || team.campus || '—' }}
                    </td>
                    <td class="px-4 py-3">
                      <p class="font-medium text-ink-gray-8">
                        {{ team.member_count }}
                      </p>
                      <p
                        class="max-w-[240px] truncate text-xs text-ink-gray-5"
                        :title="team.member_names?.join(', ')"
                      >
                        {{ team.member_names?.join(', ') || __('Chưa có') }}
                      </p>
                    </td>
                    <td class="px-4 py-3 text-ink-gray-7">
                      {{ team.zone_count }}
                    </td>
                    <td class="px-4 py-3">
                      <span
                        :class="
                          team.is_active
                            ? 'bg-green-50 text-green-700'
                            : 'bg-surface-gray-2 text-ink-gray-6'
                        "
                        class="rounded-full px-2 py-1 text-xs font-medium"
                      >
                        {{
                          team.is_active ? __('Đang hoạt động') : __('Đã tắt')
                        }}
                      </span>
                    </td>
                    <td class="px-4 py-3 text-right">
                      <Button
                        variant="subtle"
                        size="sm"
                        :label="__('Sửa')"
                        iconLeft="edit-2"
                        @click="openTeam(team)"
                      />
                    </td>
                  </tr>
                  <tr v-if="!data?.teams?.length">
                    <td
                      colspan="6"
                      class="px-4 py-8 text-center text-sm text-ink-gray-5"
                    >
                      {{ __('Chưa có nhóm.') }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section
          id="assignment-setup-staff"
          class="order-3 rounded-lg border border-outline-gray-2 bg-surface-white"
        >
          <div class="flex items-center justify-between gap-3 p-4">
            <div class="min-w-0">
              <span class="block font-semibold text-ink-gray-9">{{
                __('Nhân sự')
              }}</span>
              <span class="mt-1 block text-xs text-ink-gray-5">{{
                __('Thêm người và gắn vào nhóm.')
              }}</span>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <Button
                variant="solid"
                size="sm"
                :label="__('Thêm nhân sự')"
                iconLeft="plus"
                @click="openStaff(null)"
              />
              <button
                type="button"
                class="inline-flex min-h-9 min-w-9 items-center justify-center rounded-md text-ink-gray-5 hover:bg-surface-gray-2 focus:outline-none focus:ring-2 focus:ring-outline-gray-4"
                :aria-expanded="sections.staff"
                :aria-label="
                  sections.staff ? __('Thu gọn Nhân sự') : __('Mở Nhân sự')
                "
                :title="
                  sections.staff ? __('Thu gọn Nhân sự') : __('Mở Nhân sự')
                "
                @click="toggleSection('staff')"
              >
                <FeatherIcon
                  :name="sections.staff ? 'chevron-up' : 'chevron-down'"
                  class="size-4"
                />
              </button>
            </div>
          </div>
          <div v-if="sections.staff" class="border-t border-outline-gray-1">
            <div class="overflow-x-auto">
              <table class="w-full min-w-[760px] text-sm">
                <thead
                  class="bg-surface-gray-2 text-left text-xs text-ink-gray-6"
                >
                  <tr>
                    <th class="px-4 py-3">{{ __('Nhân sự') }}</th>
                    <th class="px-4 py-3">{{ __('Tài khoản') }}</th>
                    <th class="px-4 py-3">{{ __('Nhóm') }}</th>
                    <th class="px-4 py-3">{{ __('Chức năng') }}</th>
                    <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
                    <th class="px-4 py-3 text-right">{{ __('Thao tác') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="staff in data?.staff || []"
                    :key="staff.id"
                    class="border-t border-outline-gray-1 align-top"
                  >
                    <td class="px-4 py-3 font-medium text-ink-gray-9">
                      {{ staff.full_name }}
                    </td>
                    <td class="px-4 py-3 text-ink-gray-6">{{ staff.user }}</td>
                    <td class="px-4 py-3 text-ink-gray-7">
                      {{ staff.team_names?.join(', ') || __('Chưa có nhóm') }}
                    </td>
                    <td class="px-4 py-3 text-ink-gray-7">
                      {{ staff.functions?.join(', ') || '—' }}
                    </td>
                    <td class="px-4 py-3">
                      <span
                        :class="
                          staff.is_active ? 'text-green-700' : 'text-ink-gray-5'
                        "
                        >{{
                          staff.is_active ? __('Đang hoạt động') : __('Đã tắt')
                        }}</span
                      >
                    </td>
                    <td class="px-4 py-3 text-right">
                      <Button
                        variant="subtle"
                        size="sm"
                        :label="__('Sửa')"
                        iconLeft="edit-2"
                        @click="openStaff(staff)"
                      />
                    </td>
                  </tr>
                  <tr v-if="!data?.staff?.length">
                    <td
                      colspan="6"
                      class="px-4 py-8 text-center text-sm text-ink-gray-5"
                    >
                      {{ __('Chưa có nhân sự.') }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section
          id="assignment-setup-zone"
          class="order-1 rounded-lg border border-outline-gray-2 bg-surface-white"
        >
          <div class="flex items-center justify-between gap-3 p-4">
            <div class="min-w-0">
              <span class="block font-semibold text-ink-gray-9">{{
                __('Địa bàn')
              }}</span>
              <span class="mt-1 block text-xs text-ink-gray-5">{{
                __('Tạo cụm, tạo khu vực và gán nhóm phụ trách.')
              }}</span>
            </div>
            <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
              <Button
                v-if="canManage"
                variant="solid"
                size="sm"
                :label="__('Tạo cụm')"
                iconLeft="plus"
                @click="openGeography('cluster')"
              />
              <Button
                v-if="canManage"
                variant="subtle"
                size="sm"
                :label="__('Tạo khu vực')"
                iconLeft="plus"
                :disabled="!activeClusters.length"
                @click="openGeography('zone')"
              />
              <button
                type="button"
                class="inline-flex min-h-9 min-w-9 items-center justify-center rounded-md text-ink-gray-5 hover:bg-surface-gray-2 focus:outline-none focus:ring-2 focus:ring-outline-gray-4"
                :aria-expanded="sections.zone"
                :aria-label="
                  sections.zone ? __('Thu gọn địa bàn') : __('Mở địa bàn')
                "
                :title="
                  sections.zone ? __('Thu gọn địa bàn') : __('Mở địa bàn')
                "
                @click="toggleSection('zone')"
              >
                <FeatherIcon
                  :name="sections.zone ? 'chevron-up' : 'chevron-down'"
                  class="size-4"
                />
              </button>
            </div>
          </div>
          <div v-if="sections.zone" class="border-t border-outline-gray-1">
            <div class="border-b border-outline-gray-1 p-4">
              <div class="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 class="font-medium text-ink-gray-9">{{ __('Cụm') }}</h3>
                  <p class="mt-1 text-xs text-ink-gray-5">
                    {{ __('Một cụm gồm nhiều khu vực trong cùng Tỉnh/TP.') }}
                  </p>
                </div>
                <span class="text-xs text-ink-gray-5">
                  {{ data?.clusters?.length || 0 }} {{ __('cụm') }}
                </span>
              </div>
              <div class="overflow-x-auto">
                <table class="w-full min-w-[640px] text-sm">
                  <thead
                    class="bg-surface-gray-2 text-left text-xs text-ink-gray-6"
                  >
                    <tr>
                      <th class="px-4 py-3">{{ __('Cụm') }}</th>
                      <th class="px-4 py-3">{{ __('Tỉnh/TP') }}</th>
                      <th class="px-4 py-3">{{ __('Khu vực') }}</th>
                      <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="cluster in data?.clusters || []"
                      :key="cluster.id"
                      class="border-t border-outline-gray-1"
                    >
                      <td class="px-4 py-3 font-medium text-ink-gray-9">
                        {{ cluster.cluster_name }}
                      </td>
                      <td class="px-4 py-3 text-ink-gray-7">
                        {{ cluster.province_name || cluster.province || '—' }}
                      </td>
                      <td class="px-4 py-3 text-ink-gray-7">
                        {{ cluster.zone_count }}
                      </td>
                      <td class="px-4 py-3">
                        <span
                          class="rounded-full px-2 py-1 text-xs font-medium"
                          :class="
                            cluster.is_active
                              ? 'bg-green-50 text-green-700'
                              : 'bg-surface-gray-2 text-ink-gray-6'
                          "
                        >
                          {{
                            cluster.is_active
                              ? __('Đang hoạt động')
                              : __('Đã tắt')
                          }}
                        </span>
                      </td>
                    </tr>
                    <tr v-if="!data?.clusters?.length">
                      <td
                        colspan="4"
                        class="px-4 py-6 text-center text-sm text-ink-gray-5"
                      >
                        {{
                          __('Chưa có cụm. Hãy tạo cụm trước khi tạo khu vực.')
                        }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full min-w-[760px] text-sm">
                <thead
                  class="bg-surface-gray-2 text-left text-xs text-ink-gray-6"
                >
                  <tr>
                    <th class="px-4 py-3">{{ __('Khu vực') }}</th>
                    <th class="px-4 py-3">{{ __('Cụm') }}</th>
                    <th class="px-4 py-3">{{ __('Tỉnh/TP') }}</th>
                    <th class="px-4 py-3">{{ __('Nhóm phụ trách') }}</th>
                    <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
                    <th class="px-4 py-3 text-right">{{ __('Thao tác') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="zone in data?.zones || []"
                    :key="zone.id"
                    class="border-t border-outline-gray-1"
                  >
                    <td class="px-4 py-3 font-medium text-ink-gray-9">
                      {{ zone.zone_name }}
                    </td>
                    <td class="px-4 py-3 text-ink-gray-7">
                      {{ zone.cluster_name || zone.cluster || '—' }}
                    </td>
                    <td class="px-4 py-3 text-ink-gray-7">
                      {{ zone.province_name || zone.province || '—' }}
                    </td>
                    <td class="px-4 py-3 text-ink-gray-7">
                      {{ zone.team_name || __('Chưa gán') }}
                    </td>
                    <td class="px-4 py-3">
                      <span
                        :class="
                          zone.team
                            ? 'bg-green-50 text-green-700'
                            : 'bg-orange-50 text-orange-700'
                        "
                        class="rounded-full px-2 py-1 text-xs font-medium"
                      >
                        {{ zone.team ? __('Đã gán') : __('Chưa gán') }}
                      </span>
                    </td>
                    <td class="px-4 py-3 text-right">
                      <Button
                        variant="subtle"
                        size="sm"
                        :label="__('Gán nhóm')"
                        iconLeft="link-2"
                        :disabled="!editOptions?.teams?.length"
                        @click="openZone(zone)"
                      />
                    </td>
                  </tr>
                  <tr v-if="!data?.zones?.length">
                    <td
                      colspan="6"
                      class="px-4 py-8 text-center text-sm text-ink-gray-5"
                    >
                      {{ __('Chưa có khu vực.') }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p
              class="border-t border-outline-gray-1 px-4 py-3 text-xs text-ink-gray-5"
            >
              {{
                __(
                  'Tạo mới chỉ thêm khung địa bàn, không thay đổi dữ liệu trường.',
                )
              }}
            </p>
          </div>
        </section>

        <section
          id="assignment-setup-pool"
          class="order-4 rounded-lg border border-outline-gray-2 bg-surface-white"
        >
          <div class="flex items-center justify-between gap-3 p-4">
            <div class="min-w-0">
              <span class="block font-semibold text-ink-gray-9">{{
                __('Hàng chờ')
              }}</span>
              <span class="mt-1 block text-xs text-ink-gray-5">{{
                __('Nơi Lead mới chờ để được chia cho Sale trong nhóm.')
              }}</span>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <Button
                v-if="canManage"
                variant="solid"
                size="sm"
                :label="__('Tạo hàng chờ')"
                iconLeft="plus"
                :disabled="!salesTeams.length"
                @click="poolModalOpen = true"
              />
              <button
                type="button"
                class="inline-flex min-h-9 min-w-9 items-center justify-center rounded-md text-ink-gray-5 hover:bg-surface-gray-2 focus:outline-none focus:ring-2 focus:ring-outline-gray-4"
                :aria-expanded="sections.pool"
                :aria-label="
                  sections.pool ? __('Thu gọn hàng chờ') : __('Mở hàng chờ')
                "
                :title="
                  sections.pool ? __('Thu gọn hàng chờ') : __('Mở hàng chờ')
                "
                @click="toggleSection('pool')"
              >
                <FeatherIcon
                  :name="sections.pool ? 'chevron-up' : 'chevron-down'"
                  class="size-4"
                />
              </button>
            </div>
          </div>
          <div v-if="sections.pool" class="border-t border-outline-gray-1">
            <div class="overflow-x-auto">
              <table class="w-full min-w-[760px] text-sm">
                <thead
                  class="bg-surface-gray-2 text-left text-xs text-ink-gray-6"
                >
                  <tr>
                    <th class="px-4 py-3">{{ __('Hàng chờ') }}</th>
                    <th class="px-4 py-3">{{ __('Nhóm') }}</th>
                    <th class="px-4 py-3">{{ __('Cơ sở') }}</th>
                    <th class="px-4 py-3">{{ __('Trạng thái') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="pool in data?.pools || []"
                    :key="pool.id"
                    class="border-t border-outline-gray-1"
                  >
                    <td class="px-4 py-3 font-medium text-ink-gray-9">
                      {{ pool.pool_name }}
                    </td>
                    <td class="px-4 py-3 text-ink-gray-7">
                      {{ pool.team_name || pool.team || '—' }}
                    </td>
                    <td class="px-4 py-3 text-ink-gray-7">
                      {{ pool.campus_name || pool.campus || '—' }}
                    </td>
                    <td class="px-4 py-3">
                      <span
                        class="rounded-full px-2 py-1 text-xs font-medium"
                        :class="
                          pool.is_active
                            ? 'bg-green-50 text-green-700'
                            : 'bg-surface-gray-2 text-ink-gray-6'
                        "
                      >
                        {{
                          pool.is_active ? __('Đang hoạt động') : __('Đã tắt')
                        }}
                      </span>
                    </td>
                  </tr>
                  <tr v-if="!data?.pools?.length">
                    <td
                      colspan="4"
                      class="px-4 py-8 text-center text-sm text-ink-gray-5"
                    >
                      {{ __('Chưa có hàng chờ.') }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p
              class="border-t border-outline-gray-1 px-4 py-3 text-xs text-ink-gray-5"
            >
              {{
                __(
                  'Hàng chờ chỉ nhận Lead sau khi được chọn trong Cách chia Lead.',
                )
              }}
            </p>
          </div>
        </section>
      </template>
    </template>

    <TeamSetupModal
      v-model="teamModalOpen"
      :team="selectedTeam"
      :options="data?.options"
      :staff="data?.staff || []"
      :teams="data?.teams || []"
      @saved="$emit('refresh')"
    />
    <StaffContextModal
      v-model="staffModalOpen"
      :row="staffContextRow"
      @saved="$emit('refresh')"
    />
    <EditAssignmentModal
      v-model="zoneModalOpen"
      :row="selectedZone"
      :options="editOptions"
      @applied="$emit('refresh')"
    />
    <GeographySetupModal
      v-model="geographyModalOpen"
      :kind="geographyKind"
      :options="data?.options"
      @saved="$emit('refresh')"
    />
    <StudentPoolSetupModal
      v-model="poolModalOpen"
      :teams="data?.teams || []"
      @saved="$emit('refresh')"
    />
  </section>
</template>

<script setup>
import { Button, FeatherIcon } from 'frappe-ui'
import { computed, reactive, ref } from 'vue'
import EditAssignmentModal from './EditAssignmentModal.vue'
import GeographySetupModal from './GeographySetupModal.vue'
import StaffContextModal from './StaffContextModal.vue'
import StudentPoolSetupModal from './StudentPoolSetupModal.vue'
import TeamSetupModal from './TeamSetupModal.vue'

const props = defineProps({
  data: { type: Object, default: null },
  control: { type: Object, default: null },
  loading: Boolean,
  error: { type: [Object, String], default: null },
  canManage: Boolean,
  workflowOnly: Boolean,
})
const emit = defineEmits(['refresh', 'navigate'])

const teamModalOpen = ref(false)
const staffModalOpen = ref(false)
const zoneModalOpen = ref(false)
const geographyModalOpen = ref(false)
const geographyKind = ref('cluster')
const poolModalOpen = ref(false)
const selectedTeam = ref(null)
const selectedStaff = ref(null)
const selectedZone = ref(null)
const sections = reactive({
  zone: true,
  team: false,
  staff: false,
  pool: false,
})

const workflowSteps = computed(() => {
  const summary = props.data?.summary || {}
  const checks = props.control?.checks || []
  const checkPassed = (code) =>
    Boolean(checks.find((item) => item.code === code)?.passed)
  return [
    {
      key: 'zone',
      number: 1,
      label: __('Khu vực'),
      description: __('Gán nhóm tư vấn cho từng khu vực.'),
      done: Boolean(summary.zones) && summary.mapped_zones === summary.zones,
      section: 'zone',
    },
    {
      key: 'team',
      number: 2,
      label: __('Nhóm tư vấn'),
      description: __('Tạo nhóm và chọn cơ sở hoạt động.'),
      done: Number(summary.active_teams || 0) > 0,
      section: 'team',
    },
    {
      key: 'staff',
      number: 3,
      label: __('Nhân sự'),
      description: __('Thêm người và gắn vào nhóm.'),
      done: checkPassed('eligible_staff'),
      section: 'staff',
    },
    {
      key: 'load',
      number: 4,
      label: __('Giới hạn nhận'),
      description: __('Đặt số Lead tối đa mỗi người đang giữ.'),
      done: checkPassed('capacity_configured'),
      tab: 'load',
    },
    {
      key: 'policy',
      number: 5,
      label: __('Cách chia Lead'),
      description: __('Chọn cách chia Lead cho hàng chờ.'),
      done: checkPassed('active_policy'),
      tab: 'policy',
    },
    {
      key: 'control',
      number: 6,
      label: __('Bật tự động'),
      description: __('Bật khi 5 bước trước đã hoàn tất.'),
      done: Boolean(props.control?.enabled),
      tab: 'control',
    },
  ]
})
const completedSteps = computed(
  () => workflowSteps.value.filter((step) => step.done).length,
)

const editOptions = computed(
  () => props.data?.edit_options || { teams: [], staff: [] },
)
const salesTeams = computed(() =>
  (props.data?.teams || []).filter(
    (team) => team.is_active && team.team_type === 'Sales',
  ),
)
const activeClusters = computed(() =>
  (props.data?.clusters || []).filter((cluster) => cluster.is_active),
)
const summaryCards = computed(() => [
  { label: __('Cụm'), value: props.data?.summary?.clusters || 0 },
  {
    label: __('Khu vực'),
    value: `${props.data?.summary?.mapped_zones || 0}/${props.data?.summary?.zones || 0}`,
  },
  { label: __('Nhóm'), value: props.data?.summary?.teams || 0 },
  { label: __('Hàng chờ'), value: props.data?.summary?.pools || 0 },
])
const staffContextRow = computed(() => {
  if (!selectedStaff.value) return null
  return {
    full_name: selectedStaff.value.full_name,
    user: selectedStaff.value.user,
    crm_staff: { name: selectedStaff.value.id },
  }
})

function openTeam(team) {
  selectedTeam.value = team
  teamModalOpen.value = true
}

function openStaff(staff) {
  selectedStaff.value = staff
  staffModalOpen.value = true
}

function openZone(zone) {
  selectedZone.value = {
    level: 'zone',
    zone_id: zone.id,
    label: zone.zone_name,
    team_id: zone.team,
    team_name: zone.team_name,
    revision: zone.revision || '0',
    active_students: 0,
  }
  zoneModalOpen.value = true
}

function openGeography(kind) {
  geographyKind.value = kind
  geographyModalOpen.value = true
}

function toggleSection(section) {
  sections[section] = !sections[section]
}

function openStep(step) {
  if (step.section) {
    if (props.workflowOnly) {
      emit('navigate', 'setup')
      return
    }
    sections[step.section] = true
    document
      .getElementById(`assignment-setup-${step.section}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }
  if (step.tab) emit('navigate', step.tab)
}

function errorMessage(error) {
  return (
    error?.messages?.join?.(' ') ||
    error?.message ||
    String(error || __('Lỗi không xác định'))
  )
}
</script>
