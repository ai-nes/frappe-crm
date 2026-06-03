<template>
  <div
    class="grid h-full place-items-center px-4 py-20 text-center text-lg text-ink-gray-5"
  >
    <div class="space-y-2">
      <div>{{ __('Invalid page or not permitted to access') }}</div>
      <Button
        :route="{ name: 'CRM Contacts' }"
        :label="__('CRM Contacts')"
        :iconLeft="ContactsIcon"
      />
    </div>
  </div>
</template>

<script setup>
import ContactsIcon from '@/components/Icons/ContactsIcon.vue'
</script>
