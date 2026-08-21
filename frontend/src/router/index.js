import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '@/views/DashboardView.vue'
import IotMonitorView from '@/views/IotMonitorView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/iot', name: 'iot-monitor', component: IotMonitorView }
  ]
})

export default router
