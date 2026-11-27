<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowDown, Fold, Grid, Moon, Sunny } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '../auth'
import { api, errorMessage, roleLabels } from '../api'
import { sections } from '../router'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const collapsed = ref(localStorage.getItem('portal-nav') === 'collapsed')
const mobileOpen = ref(false)
const dark = ref(document.documentElement.classList.contains('dark'))
const healthy = ref<boolean | null>(null)
let healthTimer: number | undefined
const visibleSections = computed(() => sections.map(section => ({
  ...section, items: section.items.filter(item => !item.admin || auth.user?.role === 'admin'),
})))

watch(collapsed, value => localStorage.setItem('portal-nav', value ? 'collapsed' : 'expanded'))
watch(dark, value => {
  document.documentElement.classList.toggle('dark', value)
  localStorage.setItem('portal-theme', value ? 'dark' : 'light')
})
watch(() => route.path, () => { mobileOpen.value = false })

async function checkHealth() {
  try {
    healthy.value = (await api<{ status: string }>('/health')).status === 'healthy'
  } catch {
    healthy.value = false
  }
}

onMounted(() => {
  void checkHealth()
  healthTimer = window.setInterval(checkHealth, 45000)
})
onUnmounted(() => window.clearInterval(healthTimer))

function toggleMenu() {
  if (window.matchMedia('(max-width: 760px)').matches) mobileOpen.value = !mobileOpen.value
  else collapsed.value = !collapsed.value
}

async function account(command: string) {
  if (command === 'settings') {
    await router.push('/settings')
    return
  }
  try {
    await auth.logout()
    await router.replace('/login')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
</script>

<template>
  <div class="workspace" :class="{ collapsed, 'mobile-open': mobileOpen }">
    <button v-if="mobileOpen" class="nav-scrim" aria-label="关闭导航" @click="mobileOpen = false"></button>
    <aside class="sidebar">
      <RouterLink class="brand" to="/workbench" aria-label="企业 AI 工作台">
        <span class="brand-symbol"><el-icon><Grid /></el-icon></span>
        <span class="brand-name">企业 AI 平台</span>
      </RouterLink>
      <nav aria-label="主导航">
        <section v-for="section in visibleSections" :key="section.title" class="nav-group">
          <div class="nav-label">{{ section.title }}</div>
          <RouterLink v-for="item in section.items" :key="item.path" :to="item.path" :title="item.title" :aria-label="item.title" class="nav-item">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.title }}</span>
          </RouterLink>
        </section>
      </nav>
    </aside>
    <div class="main-area">
      <header class="topbar">
        <el-button text :icon="Fold" aria-label="切换导航" @click="toggleMenu" />
        <span class="top-title">{{ route.meta.title }}</span>
        <div class="top-actions">
          <RouterLink v-if="healthy !== null" class="top-health" to="/status">
            <el-tag :type="healthy ? 'success' : 'danger'" round>{{ healthy ? '平台在线' : '平台异常' }}</el-tag>
          </RouterLink>
          <el-button text :icon="dark ? Sunny : Moon" :aria-label="dark ? '切换浅色主题' : '切换深色主题'" @click="dark = !dark" />
          <el-dropdown v-if="auth.user" trigger="click" @command="account">
            <el-button text class="account-button">
              <span class="avatar">{{ auth.user.display_name.charAt(0) }}</span>
              <span class="account-name">{{ auth.user.display_name }} · {{ roleLabels[auth.user.role] }}</span>
              <el-icon><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="settings">个人设置</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>
      <main class="content"><RouterView /></main>
    </div>
  </div>
</template>
