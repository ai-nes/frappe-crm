<template>
  <div class="flex h-screen w-screen">
    <div class="h-full border-r bg-[--sidebar-bg]">
      <AppSidebar />
    </div>
    <div class="flex-1 flex flex-col h-full overflow-auto bg-surface-white">
      <AppHeader />
      <slot />
    </div>
    <GlobalModals />
    <AIChatbox />
  </div>
</template>
<script setup>
import AppSidebar from '@/components/Layouts/AppSidebar.vue'
import AppHeader from '@/components/Layouts/AppHeader.vue'
import GlobalModals from '@/components/Modals/GlobalModals.vue'
import AIChatbox from '@/components/AIChatbox/AIChatbox.vue'
</script>
