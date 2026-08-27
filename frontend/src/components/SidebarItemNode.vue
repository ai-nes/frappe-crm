<template>
  <div class="flex flex-col select-none">
    <!-- Main Node Item -->
    <div
      class="group relative flex h-7.5 cursor-pointer items-center rounded text-ink-gray-8 transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
      :class="[
        isActive ? 'bg-surface-selected font-medium text-ink-gray-9 shadow-sm' : 'hover:bg-surface-gray-2',
        depth > 0 ? 'ml-4 pl-1 text-xs' : '',
        isCollapsed ? 'justify-center mx-1 px-1' : 'mx-2 px-2 py-[7px]'
      ]"
      @click="handleClick"
    >
      <div
        class="flex w-full items-center justify-between overflow-hidden"
        :class="isCollapsed ? 'justify-center' : ''"
      >
        <div class="flex items-center min-w-0 truncate">
          <!-- Icon -->
          <Tooltip :text="__(item.label)" placement="right" :disabled="!isCollapsed">
            <div class="flex items-center justify-center shrink-0">
              <component
                :is="resolvedIcon"
                v-if="resolvedIcon"
                class="size-4 shrink-0 transition-transform duration-200"
                :class="[
                  isActive ? 'text-ink-gray-9' : 'text-ink-gray-7 group-hover:text-ink-gray-9',
                  isCollapsed ? 'size-4' : 'size-4'
                ]"
              />
              <div
                v-else-if="depth > 0"
                class="size-1.5 rounded-full bg-ink-gray-4 group-hover:bg-ink-gray-7 shrink-0 mr-1"
                :class="{ '!bg-ink-gray-9': isActive }"
              />
            </div>
          </Tooltip>

          <!-- Label -->
          <Tooltip
            :text="__(item.label)"
            placement="right"
            :disabled="isCollapsed"
            :hoverDelay="1.5"
          >
            <span
              v-if="!isCollapsed"
              class="truncate text-sm transition-all duration-300 ease-in-out"
              :class="[
                depth > 0 ? 'ml-2 text-xs text-ink-gray-7 group-hover:text-ink-gray-9' : 'ml-2.5 text-sm',
                isActive ? 'font-medium text-ink-gray-9' : ''
              ]"
            >
              {{ __(item.label) }}
            </span>
          </Tooltip>
        </div>

        <!-- Right Side: Badge & Expand Chevron -->
        <div v-if="!isCollapsed" class="flex items-center gap-1.5 shrink-0 ml-1.5">
          <!-- Badge -->
          <Badge
            v-if="badgeCount"
            :label="badgeCount"
            :variant="item.badgeVariant === 'red' ? 'solid' : 'subtle'"
            :theme="item.badgeVariant === 'red' ? 'red' : item.badgeVariant === 'orange' ? 'orange' : 'gray'"
            size="sm"
            class="scale-90 font-medium"
          />

          <!-- Chevron for expandable children -->
          <button
            v-if="hasChildren"
            type="button"
            class="p-0.5 rounded hover:bg-surface-gray-3 text-ink-gray-5 transition-transform duration-200"
            :class="{ 'rotate-90 text-ink-gray-8': isExpanded }"
            @click.stop="toggleExpand"
          >
            <ChevronRightIcon class="size-3.5" />
          </button>
        </div>

        <!-- Collapsed Badge Dot Indicator -->
        <div
          v-else-if="badgeCount"
          class="absolute top-1.5 right-1.5 size-2 rounded-full ring-2 ring-white"
          :class="item.badgeVariant === 'red' ? 'bg-surface-red-5' : 'bg-surface-gray-6'"
        />
      </div>
    </div>

    <!-- Children Nodes (Collapsible Submenu) -->
    <div
      v-if="hasChildren && isExpanded && !isCollapsed"
      class="flex flex-col space-y-[2px] mt-0.5 mb-1 transition-all duration-300 ease-in-out"
    >
      <SidebarItemNode
        v-for="child in item.children"
        :key="child.id || child.label"
        :item="child"
        :isCollapsed="isCollapsed"
        :isMobile="isMobile"
        :depth="depth + 1"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, markRaw } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Tooltip, Badge } from 'frappe-ui'
import { useNavigationBadgesStore } from '@/stores/navigationBadges'
import { mobileSidebarOpened } from '@/composables/settings'

// Import Lucide Icons
import FlameIcon from '~icons/lucide/flame'
import ClipboardListIcon from '~icons/lucide/clipboard-list'
import InboxIcon from '~icons/lucide/inbox'
import ListChecksIcon from '~icons/lucide/list-checks'
import CalendarIcon from '~icons/lucide/calendar'
import LayoutDashboardIcon from '~icons/lucide/layout-dashboard'
import BookOpenIcon from '~icons/lucide/book-open'
import ClockIcon from '~icons/lucide/clock'
import UsersIcon from '~icons/lucide/users'
import GitForkIcon from '~icons/lucide/git-fork'
import UserCheckIcon from '~icons/lucide/user-check'
import LinkIcon from '~icons/lucide/link'
import BarChart3Icon from '~icons/lucide/bar-chart-3'
import ShieldCheckIcon from '~icons/lucide/shield-check'
import LineChartIcon from '~icons/lucide/line-chart'
import MegaphoneIcon from '~icons/lucide/megaphone'
import CoinsIcon from '~icons/lucide/coins'
import SearchIcon from '~icons/lucide/search'
import FilterIcon from '~icons/lucide/filter'
import SendIcon from '~icons/lucide/send'
import TargetIcon from '~icons/lucide/target'
import PieChartIcon from '~icons/lucide/pie-chart'
import PenToolIcon from '~icons/lucide/pen-tool'
import GraduationCapIcon from '~icons/lucide/graduation-cap'
import SlidersIcon from '~icons/lucide/sliders'
import BarChart2Icon from '~icons/lucide/bar-chart-2'
import UserCogIcon from '~icons/lucide/user-cog'
import BuildingIcon from '~icons/lucide/building'
import PlugIcon from '~icons/lucide/plug'
import KeyIcon from '~icons/lucide/key'
import DatabaseIcon from '~icons/lucide/database'
import ActivityIcon from '~icons/lucide/activity'
import HardDriveIcon from '~icons/lucide/hard-drive'
import LockIcon from '~icons/lucide/lock'
import EyeIcon from '~icons/lucide/eye'
import ChevronRightIcon from '~icons/lucide/chevron-right'

const props = defineProps({
  item: { type: Object, required: true },
  isCollapsed: { type: Boolean, default: false },
  isMobile: { type: Boolean, default: false },
  depth: { type: Number, default: 0 },
})

const router = useRouter()
const route = useRoute()
const badgesStore = useNavigationBadgesStore()

const isExpanded = ref(false)
const hasChildren = computed(() => Boolean(props.item.children?.length))

const iconMap = {
  flame: FlameIcon,
  'clipboard-list': ClipboardListIcon,
  inbox: InboxIcon,
  'list-checks': ListChecksIcon,
  calendar: CalendarIcon,
  'layout-dashboard': LayoutDashboardIcon,
  'book-open': BookOpenIcon,
  clock: ClockIcon,
  users: UsersIcon,
  'git-fork': GitForkIcon,
  'user-check': UserCheckIcon,
  link: LinkIcon,
  'bar-chart-3': BarChart3Icon,
  'shield-check': ShieldCheckIcon,
  'line-chart': LineChartIcon,
  megaphone: MegaphoneIcon,
  coins: CoinsIcon,
  search: SearchIcon,
  filter: FilterIcon,
  send: SendIcon,
  target: TargetIcon,
  'pie-chart': PieChartIcon,
  'pen-tool': PenToolIcon,
  'graduation-cap': GraduationCapIcon,
  sliders: SlidersIcon,
  'bar-chart-2': BarChart2Icon,
  'user-cog': UserCogIcon,
  building: BuildingIcon,
  plug: PlugIcon,
  key: KeyIcon,
  database: DatabaseIcon,
  activity: ActivityIcon,
  'hard-drive': HardDriveIcon,
  lock: LockIcon,
  eye: EyeIcon,
}

const resolvedIcon = computed(() => {
  if (!props.item.icon) return null
  if (typeof props.item.icon === 'object' || typeof props.item.icon === 'function') {
    return markRaw(props.item.icon)
  }
  const component = iconMap[props.item.icon]
  return component ? markRaw(component) : null
})

const badgeCount = computed(() => {
  if (props.item.badgeKey) {
    return badgesStore.getBadge(props.item.badgeKey)
  }
  return null
})

function checkRouteMatch(to) {
  if (!to) return false
  if (typeof to === 'string') {
    return route.name === to
  }
  if (to.name && route.name === to.name) {
    if (to.query) {
      for (const [k, v] of Object.entries(to.query)) {
        if (route.query[k] !== v) return false
      }
    }
    if (to.params) {
      for (const [k, v] of Object.entries(to.params)) {
        if (route.params[k] !== v) return false
      }
    }
    return true
  }
  return false
}

const isActive = computed(() => {
  if (checkRouteMatch(props.item.to)) return true
  // Check if any child is active
  if (props.item.children) {
    return props.item.children.some((child) => checkRouteMatch(child.to))
  }
  return false
})

function toggleExpand() {
  isExpanded.value = !isExpanded.value
}

function handleClick() {
  if (hasChildren.value && !props.isCollapsed) {
    toggleExpand()
    if (!props.item.to && !props.item.action) return
  }

  if (props.item.action) {
    props.item.action()
    if (props.isMobile) {
      mobileSidebarOpened.value = false
    }
    return
  }

  if (props.item.to) {
    if (typeof props.item.to === 'object') {
      router.push(props.item.to)
    } else {
      router.push({ name: props.item.to })
    }
    if (props.isMobile) {
      mobileSidebarOpened.value = false
    }
  }
}
</script>

