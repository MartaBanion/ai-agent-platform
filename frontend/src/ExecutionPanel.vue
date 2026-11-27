<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { api, errorMessage } from './api'
import { isAbort, stream, type Execution, type ModelOption } from './ai'
import Markdown from './Markdown.vue'
import ReferenceList from './ReferenceList.vue'
import { useAuth } from './auth'
import type { Knowledge, Reference, ToolCall } from './resources'

const props = defineProps<{ path: string; needsModel?: boolean; models?: ModelOption[]; agentId?: string }>()
const auth = useAuth()
const text = ref('')
const model = ref('')
const result = ref('')
const error = ref('')
const history = ref<Execution[]>([])
const running = ref(false)
const retrieving = ref(false)
const references = ref<Reference[]>([])
const libraries = ref<Knowledge[]>([])
const receipts = ref<ToolCall[]>([])
const knowledge = ref('')
const toolCall = ref('')
let controller: AbortController | undefined
let executionId = ''

async function load() {
  const path = props.path
  try {
    const rows = await api<Execution[]>(path + '/history')
    if (props.path === path) history.value = rows
  } catch (cause) { error.value = errorMessage(cause) }
}

async function execute() {
  executionId = ''
  controller = new AbortController()
  running.value = true
  result.value = ''
  references.value = []
  error.value = ''
  try {
    const data = { text: text.value, ...(props.needsModel ? { model_id: model.value || null, knowledge_id: knowledge.value || null } : {}),
      ...(props.agentId && toolCall.value ? { tool_call_id: toolCall.value } : {}) }
    await stream(props.path + '/run', data, controller.signal, delta => result.value += delta,
      (id, sources) => { executionId = id; references.value = sources })
  } catch (cause) {
    error.value = isAbort(cause) ? '已停止' : errorMessage(cause)
  } finally {
    running.value = false
    await load()
  }
}

async function retrieve() {
  if (!props.agentId || !text.value.trim()) return
  error.value = ''
  retrieving.value = true
  try {
    references.value = await api(props.path + '/knowledge-context', 'POST', { text: text.value.slice(0, 1600) }, 35000)
    if (!references.value.length) error.value = '没有可访问且达到阈值的资料'
  } catch (cause) { error.value = errorMessage(cause) }
  finally { retrieving.value = false }
}

async function choices() {
  try {
    if (props.needsModel) libraries.value = (await api<Knowledge[]>('/knowledge')).filter(row => row.enabled)
    if (props.agentId) receipts.value = (await api<ToolCall[]>('/mcp/calls'))
      .filter(row => row.agent_id === props.agentId && row.owner_id === auth.user?.id && row.state === 'success')
  } catch (cause) { error.value = errorMessage(cause) }
}

async function stop() {
  try {
    if (executionId) await api('/executions/' + executionId + '/stop', 'POST')
    else controller?.abort()
  } catch { controller?.abort() }
}

watch(() => props.path, () => {
  controller?.abort(); text.value = ''; result.value = ''; history.value = []; references.value = []; void load(); void choices()
}, { immediate: true })
onUnmounted(() => controller?.abort())

const labels: Record<string, string> = { success: '成功', failed: '失败', running: '运行中', cancelled: '已取消' }
</script>

<template>
  <form class="ai-form" @submit.prevent="execute">
    <label v-if="needsModel" class="form-wide">模型 <select v-model="model">
      <option value="">默认模型</option><option v-for="option in models" :key="option.id" :value="option.id">{{ option.name }}</option>
    </select></label>
    <label v-if="needsModel && libraries.length" class="form-wide">检索知识库 <select v-model="knowledge">
      <option value="">无</option><option v-for="item in libraries" :key="item.id" :value="item.id">{{ item.name }}</option>
    </select></label>
    <label v-if="agentId && receipts.length" class="form-wide">已批准并执行的工具结果 <select v-model="toolCall">
      <option value="">无</option><option v-for="item in receipts" :key="item.id" :value="item.id">
        {{ item.name }} · {{ new Date(item.created_at).toLocaleString('zh-CN') }}
      </option></select><span class="muted">仅模型流程可将结果作为参考上下文。</span></label>
    <label class="form-wide">输入 <textarea v-model="text" rows="3" required maxlength="12000" :disabled="running" /></label>
    <div class="form-wide inline-actions">
      <el-button type="primary" native-type="submit" :loading="running">执行</el-button>
      <el-button v-if="agentId" :disabled="running || !text.trim()" :loading="retrieving" @click="retrieve">检索知识</el-button>
      <el-button v-if="running" @click="stop">停止</el-button>
    </div>
  </form>
  <el-alert v-if="error" class="panel-gap" :title="error" type="error" :closable="false" />
  <Markdown v-if="result" class="result-panel" :text="result" />
  <ReferenceList :items="references" />
  <div class="section-heading"><h2>执行记录</h2><el-button text @click="load">刷新</el-button></div>
  <el-table :data="history" empty-text="暂无执行记录">
    <el-table-column label="时间" min-width="155"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template></el-table-column>
    <el-table-column label="状态" min-width="85"><template #default="{ row }">{{ labels[row.status] }}</template></el-table-column>
    <el-table-column label="耗时" min-width="85"><template #default="{ row }">{{ row.duration_ms == null ? '—' : row.duration_ms + ' ms' }}</template></el-table-column>
    <el-table-column prop="error" label="失败原因" min-width="145" />
  </el-table>
</template>
