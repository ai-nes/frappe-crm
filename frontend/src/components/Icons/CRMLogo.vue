<template>
  <img :src="logoSrc" alt="FAIP" class="rounded object-contain" />
</template>

<script setup>
// Runtime-bound path (not a literal src) so Vite treats it as a served asset
// under /assets/crm/... rather than a build-time module import.
const logoSrc = '/assets/crm/manifest/manifest-icon-512.maskable.png'
</script>
