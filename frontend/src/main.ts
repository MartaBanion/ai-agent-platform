import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElAlert, ElButton, ElDescriptions, ElDescriptionsItem, ElDialog, ElDropdown,
  ElDropdownItem, ElDropdownMenu, ElEmpty, ElIcon, ElInput, ElLoading,
  ElOption, ElPagination, ElSelect, ElSkeleton, ElSwitch, ElTable, ElTableColumn, ElTag,
} from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './style.css'
import App from './App.vue'
import { router } from './router'
import { useAuth } from './auth'

document.documentElement.classList.toggle('dark', localStorage.getItem('portal-theme') === 'dark')
const app = createApp(App)
const pinia = createPinia()
const components = {
  ElAlert, ElButton, ElDescriptions, ElDescriptionsItem, ElDialog, ElDropdown,
  ElDropdownItem, ElDropdownMenu, ElEmpty, ElIcon, ElInput, ElOption, ElPagination,
  ElSelect, ElSkeleton, ElSwitch, ElTable, ElTableColumn, ElTag,
}
for (const [name, component] of Object.entries(components)) app.component(name, component)
app.directive('loading', ElLoading.directive)
app.use(pinia).use(router)
window.addEventListener('platform:unauthorized', () => {
  useAuth(pinia).user = null
  void router.replace('/login')
})
app.mount('#app')
