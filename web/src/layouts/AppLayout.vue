<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppSidebar from '../components/AppSidebar.vue'

type Page = 'evaluate' | 'runs' | 'datasets'

defineProps<{ page: Page }>()
const router = useRouter()
const navigationOpen = ref(false)

function navigate(page: Page) {
  navigationOpen.value = false
  router.push(page === 'datasets' ? '/datasets' : page === 'runs' ? '/runs' : '/')
}
</script>

<template>
  <div class="shell">
    <AppSidebar :page="page" :open="navigationOpen" @navigate="navigate" @close="navigationOpen = false" />
    <button v-if="navigationOpen" class="sidebar-backdrop" type="button" aria-label="关闭导航" @click="navigationOpen = false"></button>
    <div class="app-content">
      <header class="page-header">
        <button class="mobile-menu" type="button" aria-label="打开导航" aria-controls="app-navigation" :aria-expanded="navigationOpen" data-testid="mobile-menu" @click="navigationOpen = true">
          <span></span><span></span><span></span>
        </button>
        <div>
          <p class="eyebrow">{{ page === 'evaluate' ? 'EVALUATION WORKSPACE' : page === 'runs' ? 'RUN ACTIVITY' : 'DATASET WORKSPACE' }}</p>
          <h1>{{ page === 'evaluate' ? 'AgentGate 评估台' : page === 'runs' ? '运行队列' : '测评集管理' }}</h1>
          <p>{{ page === 'evaluate' ? '配置评估对象，运行用例，并用可追溯指标判断是否达到发布门槛。' : page === 'runs' ? '跟踪排队、执行进度与最近结果。' : '维护测评集、不可变版本与可复用测试用例。' }}</p>
        </div>
      </header>
      <slot />
    </div>
  </div>
</template>
