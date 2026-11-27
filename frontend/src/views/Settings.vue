<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorMessage, roleLabels } from '../api'
import { useAuth } from '../auth'

const auth = useAuth()
const router = useRouter()
const current = ref('')
const next = ref('')
const loading = ref(false)
const error = ref('')

async function save() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    await api('/auth/password', 'POST', { current_password: current.value, new_password: next.value })
    auth.user = null
    await router.replace('/login')
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    loading.value = false
    current.value = ''
    next.value = ''
  }
}
</script>

<template>
  <section>
    <div class="page-heading"><h1>系统设置</h1></div>
    <div v-if="auth.user" class="surface settings">
      <h2>个人资料</h2>
      <el-descriptions :column="1">
        <el-descriptions-item label="用户名">{{ auth.user.username }}</el-descriptions-item>
        <el-descriptions-item label="显示名称">{{ auth.user.display_name }}</el-descriptions-item>
        <el-descriptions-item label="角色">{{ roleLabels[auth.user.role] }}</el-descriptions-item>
      </el-descriptions>
      <h2>修改密码</h2>
      <p class="muted">修改后需要重新登录，其他会话也将退出。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <form class="login-form" @submit.prevent="save">
        <label for="current-password">当前密码</label>
        <el-input id="current-password" v-model="current" type="password" autocomplete="current-password" maxlength="128" required />
        <label for="next-password">新密码（至少 12 个字符）</label>
        <el-input id="next-password" v-model="next" type="password" autocomplete="new-password" minlength="12" maxlength="128" required />
        <el-button type="primary" native-type="submit" :loading="loading">保存密码</el-button>
      </form>
    </div>
  </section>
</template>
