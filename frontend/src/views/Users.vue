<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage, roleLabels, type Role, type User } from '../api'
import { useAuth } from '../auth'

const auth = useAuth()
const users = ref<User[]>([])
const page = ref(1)
const pageSize = 20
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const formError = ref('')
const editor = ref(false)
const selected = ref<User | null>(null)
const form = reactive({ username: '', display_name: '', password: '', role: 'user' as Role, is_active: true })

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api<{ items: User[]; total: number }>('/users?limit=' + pageSize + '&offset=' + (page.value - 1) * pageSize)
    users.value = data.items
    total.value = data.total
  } catch (cause) {
    users.value = []
    error.value = errorMessage(cause)
  } finally {
    loading.value = false
  }
}

function open(user: User | null) {
  selected.value = user
  formError.value = ''
  Object.assign(form, {
    username: user?.username ?? '', display_name: user?.display_name ?? '',
    password: '', role: user?.role ?? 'user', is_active: user?.is_active ?? true,
  })
  editor.value = true
}

async function save() {
  if (saving.value) return
  saving.value = true
  formError.value = ''
  const { username, display_name, role, password, is_active } = form
  try {
    if (selected.value) {
      await api('/users/' + selected.value.id, 'PUT', { display_name, role, is_active, password: password || null })
    } else {
      await api('/users', 'POST', { username, display_name, role, password })
    }
    editor.value = false
    form.password = ''
    ElMessage.success('用户已保存')
    await load()
  } catch (cause) {
    formError.value = errorMessage(cause)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-heading">
      <div><h1>用户与权限</h1><p class="muted">创建账号、分配角色并管理账号状态。</p></div>
      <div class="heading-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button :icon="Plus" type="primary" @click="open(null)">新增用户</el-button>
      </div>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-else class="surface table-panel">
      <el-table v-loading="loading" :data="users" empty-text="暂无用户">
        <el-table-column prop="username" label="用户名" min-width="145" />
        <el-table-column prop="display_name" label="显示名称" min-width="125" />
        <el-table-column label="角色" min-width="105">
          <template #default="{ row }">{{ roleLabels[(row as User).role] }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="92">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" round>{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="115">
          <template #default="{ row }">
            <RouterLink v-if="row.id === auth.user?.id" to="/settings">个人设置</RouterLink>
            <el-button v-else link type="primary" @click="open(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" @current-change="load" />
    </div>
    <el-dialog v-model="editor" :title="selected ? '编辑用户' : '新增用户'" width="min(92vw, 460px)" destroy-on-close @closed="form.password = ''">
      <el-alert v-if="formError" :title="formError" type="error" :closable="false" />
      <form class="login-form" @submit.prevent="save">
        <label v-if="!selected" for="edit-username">用户名（3 至 48 个小写字母、数字或 . _ -）</label>
        <el-input v-if="!selected" id="edit-username" v-model="form.username" minlength="3" maxlength="48" required />
        <label for="edit-display">显示名称</label>
        <el-input id="edit-display" v-model="form.display_name" maxlength="80" required />
        <label for="edit-role">角色</label>
        <el-select id="edit-role" v-model="form.role" aria-label="角色">
          <el-option v-for="(label, role) in roleLabels" :key="role" :label="label" :value="role" />
        </el-select>
        <label for="edit-password">{{ selected ? '重置密码（留空可保留当前密码）' : '初始密码（至少 12 个字符）' }}</label>
        <el-input id="edit-password" v-model="form.password" type="password" show-password autocomplete="new-password" minlength="12" maxlength="128" :required="!selected" />
        <el-switch v-if="selected" v-model="form.is_active" active-text="账号启用" aria-label="账号启用" />
        <el-button type="primary" native-type="submit" :loading="saving">保存</el-button>
      </form>
    </el-dialog>
  </section>
</template>
