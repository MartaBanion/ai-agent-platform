<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import type { Agent, ModelOption, Workflow } from '../ai'
import ExecutionPanel from '../ExecutionPanel.vue'
import AgentResources from '../AgentResources.vue'

const user = useAuth()
const builder = computed(() => user.user?.role === 'admin' || user.user?.role === 'developer')
const items = ref<Agent[]>([])
const models = ref<ModelOption[]>([])
const workflows = ref<Workflow[]>([])
const active = ref<Agent | null>(null)
const editing = ref<Agent | null>(null)
const editor = ref(false)
const resourcesOpen = ref(false)
const resourceAgent = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const defaults = { name: '', description: '', icon: '🤖', system_prompt: '', model_id: '', workflow_id: '', enabled: true, published: false }
const form = reactive({ ...defaults })

async function load() {
  loading.value = true
  error.value = ''
  try {
    items.value = await api<Agent[]>('/agents')
    if (builder.value) {
      [models.value, workflows.value] = await Promise.all([api<ModelOption[]>('/models/options'), api<Workflow[]>('/workflows')])
    }
  } catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}

function edit(agent: Agent | null) {
  editing.value = agent
  Object.assign(form, defaults)
  if (agent) Object.assign(form, {
    name: agent.name, description: agent.description, icon: agent.icon, enabled: agent.enabled,
    published: agent.published, system_prompt: agent.system_prompt ?? '', model_id: agent.model_id ?? '',
    workflow_id: agent.workflow_id ?? '',
  })
  editor.value = true
}

async function save() {
  saving.value = true
  try {
    const data = { ...form, model_id: form.model_id || null, published: form.enabled && form.published }
    await api('/agents' + (editing.value ? '/' + editing.value.id : ''), editing.value ? 'PUT' : 'POST', data)
    await load()
    if (active.value) active.value = items.value.find(item => item.id === active.value?.id) ?? null
    editor.value = false
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
  finally { saving.value = false }
}

async function remove(agent: Agent) {
  try { await ElMessageBox.confirm('确定删除「' + agent.name + '」？', '删除智能体', { type: 'warning' }) }
  catch { return }
  try {
    await api('/agents/' + agent.id, 'DELETE')
    if (active.value?.id === agent.id) active.value = null
    await load()
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-heading"><div><h1>智能体管理</h1><p class="muted">管理智能体的模型、工作流和发布权限。</p></div>
      <el-button v-if="builder" type="primary" @click="edit(null)">创建智能体</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-skeleton v-else-if="loading && !items.length" :rows="4" animated />
    <el-empty v-else-if="!items.length" description="暂无可访问的智能体" />
    <div v-else class="agent-grid">
      <article v-for="agent in items" :key="agent.id" class="surface agent-card">
        <span class="service-icon">{{ agent.icon || '🤖' }}</span>
        <el-tag :type="agent.published ? 'success' : 'info'" round>{{ !agent.enabled ? '停用' : agent.published ? '已发布' : '草稿' }}</el-tag>
        <h2>{{ agent.name }}</h2><p v-if="agent.description" class="muted">{{ agent.description }}</p>
        <div class="inline-actions">
          <el-button link type="primary" :disabled="!agent.enabled" @click="active = agent">{{ agent.editable ? '调试与历史' : '执行与历史' }}</el-button>
          <template v-if="builder && agent.editable">
            <el-button link type="primary" @click="edit(agent)">编辑</el-button>
            <el-button link type="primary" @click="resourceAgent = agent.id; resourcesOpen = true">关联资源</el-button>
            <el-button link type="danger" @click="remove(agent)">删除</el-button>
          </template>
        </div>
      </article>
    </div>
    <div v-if="active" class="surface tool-panel"><h2>{{ active.name }}</h2>
      <ExecutionPanel :key="active.id" :path="'/agents/' + active.id" :agent-id="active.id" />
    </div>
    <el-dialog v-model="editor" :title="editing ? '编辑智能体' : '创建智能体'" width="min(92vw, 620px)">
      <form class="ai-form" @submit.prevent="save">
        <label>名称 <input v-model="form.name" required maxlength="80" /></label>
        <label>图标 <input v-model="form.icon" maxlength="16" /></label>
        <label class="form-wide">描述 <textarea v-model="form.description" rows="2" maxlength="1000" /></label>
        <label>模型 <select v-model="form.model_id"><option value="">默认模型</option>
          <option v-for="item in models" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select></label>
        <label>工作流 <select v-model="form.workflow_id" required><option disabled value="">选择工作流</option>
          <option v-for="item in workflows" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select></label>
        <label class="form-wide">系统提示词 <textarea v-model="form.system_prompt" rows="4" maxlength="6000" /></label>
        <div class="form-wide inline-actions"><label class="check-label"><input v-model="form.enabled" type="checkbox" /> 启用</label>
          <label class="check-label"><input v-model="form.published" type="checkbox" :disabled="!form.enabled" /> 发布给所有用户</label>
        </div>
        <div class="form-wide form-actions"><el-button type="primary" native-type="submit" :loading="saving">保存</el-button></div>
      </form>
    </el-dialog>
    <el-dialog v-model="resourcesOpen" title="关联知识库与工具" width="min(92vw, 640px)" destroy-on-close>
      <AgentResources v-if="resourceAgent" :agent-id="resourceAgent" @saved="resourcesOpen = false" />
    </el-dialog>
  </section>
</template>
