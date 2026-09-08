import { createRouter, createWebHistory } from 'vue-router'
import EvaluationWorkspacePage from '../pages/EvaluationWorkspacePage.vue'
import RunWorkspacePage from '../pages/RunWorkspacePage.vue'
import DatasetWorkspace from '../pages/DatasetWorkspace.vue'

// Route records are established first so the existing workspace can be extracted incrementally.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'evaluate', component: EvaluationWorkspacePage },
    { path: '/runs', name: 'runs', component: RunWorkspacePage },
    { path: '/datasets', name: 'datasets', component: DatasetWorkspace },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
