<script setup lang="ts">
import { ref } from 'vue'
import { Grid, Lock, User } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../auth'
import { errorMessage } from '../api'

const auth = useAuth()
const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    await router.replace('/workbench')
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    password.value = ''
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <div class="login-brand">
      <div class="brand-symbol"><el-icon><Grid /></el-icon></div>
      <p>企业 AI 智能体平台</p>
    </div>
    <section class="login-panel">
      <h1>登录平台</h1>
      <p class="muted">使用企业账号进入工作台</p>
      <el-alert v-if="error || auth.restoreError" :title="error || auth.restoreError" type="error" :closable="false" show-icon />
      <form class="login-form" @submit.prevent="submit">
        <label for="login-user">用户名</label>
        <el-input id="login-user" v-model="username" :prefix-icon="User" autocomplete="username" maxlength="48" required />
        <label for="login-password">密码</label>
        <el-input id="login-password" v-model="password" :prefix-icon="Lock" type="password" show-password autocomplete="current-password" maxlength="128" required />
        <el-button native-type="submit" type="primary" :loading="loading">登录</el-button>
      </form>
    </section>
  </main>
</template>
