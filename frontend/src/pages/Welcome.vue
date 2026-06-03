<template>
  <div class="flex flex-col gap-5 justify-center items-center h-full">
    <div class="font-semibold text-2xl text-ink-gray-8 mb-3">
      {{ __('Welcome {0}, lets add your first student', [name]) }}
    </div>
    <div class="flex gap-3">
      <div
        class="flex flex-col px-6 pt-13 pb-7 justify-between bg-surface-gray-1 rounded-2xl items-center space-y-2 size-56"
      >
        <div class="flex flex-col items-center gap-2.5">
          <div class="flex -space-x-2">
            <div
              v-for="i in 3"
              :key="i"
              class="bg-surface-gray-3 ring-2 ring-outline-white p-2.5 rounded-full"
            >
              <AvatarIcon />
            </div>
          </div>
          <div class="text-p-base text-ink-gray-8 text-center">
            {{ __('Start with sample students') }}
          </div>
        </div>
        <Button variant="outline" :label="__('Add Sample Data')" />
      </div>
      <div
        class="flex flex-col px-6 pt-13 pb-7 justify-between bg-surface-gray-1 rounded-2xl items-center space-y-2 size-56"
      >
        <div class="flex flex-col items-center gap-2.5">
          <GoogleIcon class="" />
          <div class="text-p-base text-ink-gray-8 text-center">
            {{ __('Sync your Contacts, Email and Calendars') }}
          </div>
        </div>
        <Button variant="outline" :label="__('Connect your Email')" />
      </div>
    </div>
    <Button
      variant="ghost"
      :label="__('Or create students manually')"
      @click="router.push({ name: 'Enrollment Students', query: { stage: 'intake' } })"
    />
  </div>
</template>
<script setup>
import AvatarIcon from '@/components/Icons/AvatarIcon.vue'
import GoogleIcon from '@/components/Icons/GoogleIcon.vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const name = ref('John Doe')
const router = useRouter()
</script>
