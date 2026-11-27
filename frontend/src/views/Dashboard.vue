<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Connection, Cpu, Monitor, Refresh } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { api, errorMessage, type Overview } from '../api'
import { useAuth } from '../auth'

const route = useRoute()
const auth = useAuth()
const overview = ref<Overview | null>(null)
const error = ref('')
const loading = ref(false)
const services = computed(() => {
  if (!overview.value) return []
  const state = overview.value.services
  return [
    { name: '平台 API', description: '业务接口与身份认证', icon: Monitor, status: state.api },
    { name: 'PostgreSQL', description: '平台业务数据库', icon: Connection, status: state.database },
    { name: 'Langflow', description: '编排引擎 · ' + state.langflow.latency_ms + ' 毫秒', icon: Cpu, status: state.langflow.status },
  ]
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    overview.value = await api<Overview>('/system/overview')
  } catch (cause) {
    overview.value = null
    error.value = errorMessage(cause)
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <h1>{{ route.path === '/status' ? '系统监控' : '工作台' }}</h1>
        <p class="muted">{{ route.path === '/status' ? '查看核心服务连通性' : '你好，' + auth.user?.display_name + '。这里是你的平台运行概览。' }}</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="refresh">刷新状态</el-button>
    </div>
    <el-skeleton v-if="loading && !overview" :rows="5" animated />
    <el-alert v-else-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-empty v-else-if="!overview" description="暂无运行状态" />
    <div v-else>
      <div class="section-heading">
        <h2>核心服务</h2>
        <span class="muted">检测于 {{ new Date(overview.checked_at).toLocaleString('zh-CN') }}</span>
      </div>
      <div class="service-grid">
        <article v-for="service in services" :key="service.name" class="surface service-card">
          <div class="service-icon"><el-icon><component :is="service.icon" /></el-icon></div>
          <el-tag :type="service.status === 'available' ? 'success' : 'danger'" effect="light" round>
            {{ service.status === 'available' ? '可用' : '不可用' }}
          </el-tag>
          <div><h3>{{ service.name }}</h3><p class="muted">{{ service.description }}</p></div>
        </article>
      </div>
      <template v-if="overview.users && route.path === '/workbench'">
        <div class="section-heading"><h2>账号概览</h2><RouterLink to="/users">管理用户</RouterLink></div>
        <div class="metric-grid">
          <article class="surface metric"><span class="muted">账号总数</span><strong>{{ overview.users.total }}</strong></article>
          <article class="surface metric"><span class="muted">启用账号</span><strong>{{ overview.users.active }}</strong></article>
        </div>
      </template>
    </div>
  </section>
</template>
