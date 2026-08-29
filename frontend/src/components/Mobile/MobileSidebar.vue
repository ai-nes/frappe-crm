<template>
  <TransitionRoot :show="sidebarOpened">
    <Dialog as="div" class="fixed inset-0" @close="sidebarOpened = false">
      <TransitionChild
        as="template"
        enter="transition ease-in-out duration-200 transform"
        enter-from="-translate-x-full"
        enter-to="translate-x-0"
        leave="transition ease-in-out duration-200 transform"
        leave-from="translate-x-0"
        leave-to="-translate-x-full"
      >
        <div
          class="relative z-10 flex h-full w-[260px] flex-col justify-between border-r bg-[--sidebar-bg] transition-all duration-300 ease-in-out"
        >
          <div>
            <UserDropdown class="p-2" :isCollapsed="!sidebarOpened" />
          </div>
          <div class="flex-1 overflow-y-auto">
            <div class="mb-3 flex flex-col">
              <SidebarLink
                id="notifications-btn"
                :label="__('Notifications')"
                :icon="NotificationsIcon"
                :to="{ name: 'Notifications' }"
                class="relative mx-2 my-0.5"
              >
                <template #right>
                  <Badge
                    v-if="unreadNotificationsCount"
                    :label="unreadNotificationsCount"
                    variant="subtle"
                  />
                </template>
              </SidebarLink>
            </div>

            <!-- Role-based Navigation Tree for Mobile -->
            <nav class="flex flex-col space-y-[2px] my-2">
              <SidebarItemNode
                v-for="item in currentNavItems"
                :key="item.id || item.label"
                :item="item"
                :isCollapsed="false"
                :isMobile="true"
              />
            </nav>

            <!-- Custom Pinned & Public Views -->
            <div v-for="view in customViews" :key="view.name">
              <Section
                :label="view.name"
                :hideLabel="view.hideLabel"
                :opened="view.opened"
              >
                <template #header="{ opened, hide, toggle }">
                  <div
                    v-if="!hide"
                    class="ml-2 mt-4 flex h-7 w-auto cursor-pointer gap-1.5 px-1 text-base font-medium text-ink-gray-5 opacity-100 transition-all duration-300 ease-in-out"
                    @click="toggle()"
                  >
                    <FeatherIcon
                      name="chevron-right"
                      class="h-4 text-ink-gray-9 transition-all duration-300 ease-in-out"
                      :class="{ 'rotate-90': opened }"
                    />
                    <span>{{ __(view.name) }}</span>
                  </div>
                </template>
                <nav class="flex flex-col">
                  <SidebarLink
                    v-for="link in view.views"
                    :key="link.label"
                    :icon="link.icon"
                    :label="__(link.label)"
                    :to="link.to"
                    class="mx-2 my-0.5"
                  />
                </nav>
              </Section>
            </div>
          </div>
        </div>
      </TransitionChild>
      <TransitionChild
        as="template"
        enter="transition-opacity ease-linear duration-200"
        enter-from="opacity-0"
        enter-to="opacity-100"
        leave="transition-opacity ease-linear duration-200"
        leave-from="opacity-100"
        leave-to="opacity-0"
      >
        <DialogOverlay class="fixed inset-0 bg-surface-gray-5 bg-opacity-50" />
      </TransitionChild>
    </Dialog>
  </TransitionRoot>
</template>
<script setup>
import {
  TransitionRoot,
  TransitionChild,
  Dialog,
  DialogOverlay,
} from '@headlessui/vue'
import Section from '@/components/Section.vue'
import PinIcon from '@/components/Icons/PinIcon.vue'
import UserDropdown from '@/components/UserDropdown.vue'
import ContactsIcon from '@/components/Icons/ContactsIcon.vue'
import NoteIcon from '@/components/Icons/NoteIcon.vue'
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import NotificationsIcon from '@/components/Icons/NotificationsIcon.vue'
import GraduationCapIcon from '~icons/lucide/graduation-cap'
import UsersIcon from '~icons/lucide/users'
import UserIcon from '~icons/lucide/user'
import SchoolIcon from '~icons/lucide/school'
import MegaphoneIcon from '~icons/lucide/megaphone'
import CalendarIcon from '~icons/lucide/calendar'
import BriefcaseIcon from '~icons/lucide/briefcase'
import FilterIcon from '~icons/lucide/filter'
import SidebarLink from '@/components/SidebarLink.vue'
import SidebarItemNode from '@/components/SidebarItemNode.vue'
import { Badge, FeatherIcon } from 'frappe-ui'
import { viewsStore } from '@/stores/views'
import { unreadNotificationsCount } from '@/stores/notifications'
import { useNavigationBadgesStore } from '@/stores/navigationBadges'
import { computed, h, onMounted } from 'vue'
import { mobileSidebarOpened as sidebarOpened } from '@/composables/settings'
import { sessionStore } from '@/stores/session'
import { usersStore } from '@/stores/users'
import { canAccessNavigationRoute } from '@/utils/rolePolicy'
import { getNavigationForUser } from '@/utils/navigationConfig'

const { getPinnedViews, getPublicViews } = viewsStore()
const { user } = sessionStore()
const { getUser, users } = usersStore()
const badgesStore = useNavigationBadgesStore()

const currentUser = computed(() => getUser(user.value))

const currentNavItems = computed(() => {
  return getNavigationForUser(currentUser.value)
})

const customViews = computed(() => {
  let _views = []
  if (getPublicViews().length) {
    _views.push({
      name: 'Public Views',
      opened: true,
      views: parseView(getPublicViews()),
    })
  }

  if (getPinnedViews().length) {
    _views.push({
      name: 'Pinned Views',
      opened: true,
      views: parseView(getPinnedViews()),
    })
  }
  return _views
})

function parseView(views) {
  return views
    .filter((view) =>
      canAccessNavigationRoute(currentUser.value, view.route_name),
    )
    .map((view) => {
      return {
        label: view.label,
        icon: getIcon(view.route_name, view.icon),
        to: {
          name: view.route_name,
          params: { viewType: view.type || 'list' },
          query: { view: view.name },
        },
      }
    })
}

function getIcon(routeName, icon) {
  if (icon) return h('div', { class: 'size-auto' }, icon)

  switch (routeName) {
    case 'Contacts':
      return ContactsIcon
    case 'Notes':
      return NoteIcon
    case 'Call Logs':
      return PhoneIcon
    case 'CRM Students':
      return GraduationCapIcon
    case 'CRM Contacts':
      return UsersIcon
    case 'CRM Persons':
      return UserIcon
    case 'High Schools':
      return SchoolIcon
    case 'CRM Campaigns':
      return MegaphoneIcon
    case 'CRM Events':
      return CalendarIcon
    case 'CRM Staff':
      return BriefcaseIcon
    default:
      return PinIcon
  }
}

onMounted(async () => {
  await users.promise
  badgesStore.fetchBadges()
})
</script>
