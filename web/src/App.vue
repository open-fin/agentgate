<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import AppLayout from './layouts/AppLayout.vue'

const route = useRoute()
const router = useRouter()
const page = computed<'evaluate' | 'runs' | 'datasets'>(() =>
  route.path.startsWith('/datasets') ? 'datasets' : route.path.startsWith('/runs') ? 'runs' : 'evaluate',
)

function openReport(runId: string) {
  router.push({ path: '/', query: { runId } })
}
function runCreated() {
  router.push("/runs")
}
</script>

<template>
  <AppLayout :page="page">
    <RouterView v-slot="{ Component }">
      <component :is="Component" @open-report="openReport" @run-created="runCreated" />
    </RouterView>
  </AppLayout>
</template>
