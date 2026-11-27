<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import type { ModelOption, Workflow } from '../ai'
import ExecutionPanel from '../ExecutionPanel.vue'

const auth = useAuth()
const items = ref<Workflow[]>([])
const models = ref<ModelOption[]>([])
const chosen = ref<Workflow | null>(null)
const history = ref<{number: number; created_at: string}[]>([])
const native = ref<{id: string; name: string}[]>([])
const editor = ref(false)
const registering = ref(false)
const loading = ref(false)
const error = ref('')
const document = ref<Record<string, unknown> | null>(null)
const form = reactive({ name: '', description: '', kind: 'echo', engine_id: '' })
const mode = ref<'new' | 'attach'>('new')

async function load() {
  loading.value = true
  error.value = ''
  try {
    [items.value, models.value] = await Promise.all([api<Workflow[]>('/workflows'), api<ModelOption[]>('/models/options')])
  } catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}

async function selectItem(item: Workflow) {
  chosen.value = item
  history.value = []
  try {
    const result = await api<typeof history.value>('/workflows/' + item.id + '/versions')
    if (chosen.value?.id === item.id) history.value = result
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}

function create() {
  mode.value = 'new'
  document.value = null
  Object.assign(form, { name: '', description: '', kind: 'echo', engine_id: '' })
  editor.value = true
}

async function discover() {
  create()
  mode.value = 'attach'
  try { native.value = await api('/workflows/discovery') }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
}

async function readFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    if (file.size > 2_000_000) throw new Error()
    const data = JSON.parse(await file.text())
    if (typeof data?.name !== 'string' || !data?.data) throw new Error()
    document.value = data
    form.name = data.name.slice(0, 80)
    form.description = typeof data.description === 'string' ? data.description.slice(0, 1000) : ''
    form.kind = JSON.stringify(data.data?.nodes).includes('LanguageModelComponent') ? 'prompt' : 'echo'
  } catch { ElMessage.error('请选择有效的 Langflow JSON 文件（最大 2 MB）') }
}

async function save() {
  registering.value = true
  try {
    const item = mode.value === 'new'
      ? await api<Workflow>('/workflows', 'POST', { name: form.name, description: form.description, kind: form.kind, document: document.value })
      : await api<Workflow>('/workflows/attach', 'POST', { engine_id: form.engine_id, kind: form.kind })
    editor.value = false
    await load()
    await selectItem(item)
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
  finally { registering.value = false }
}

async function sync(item: Workflow) {
  try {
    const updated = await api<Workflow>('/workflows/' + item.id + '/sync', 'POST')
    await load()
    await selectItem(updated)
    ElMessage.success('同步完成')
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}

async function download(item: Workflow) {
  try {
    const data = await api('/workflows/' + item.id + '/export')
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = window.document.createElement('a')
    link.href = url
    link.download = 'workflow-' + item.id + '.json'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}

const editorUrl = ref('')
onMounted(async () => {
  await load()
  try { editorUrl.value = (await api<{url: string}>('/workflows/editor')).url }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
})
</script>

<template>
  <section>
    <div class="page-heading"><div><h1>工作流管理</h1><p class="muted">同步、执行并导出经审核的 Langflow 流程。</p></div>
      <div class="heading-actions">
        <a v-if="editorUrl" :href="editorUrl" target="_blank" rel="noopener noreferrer"><el-button>打开 Langflow</el-button></a>
        <el-button v-if="auth.user?.role === 'admin'" @click="discover">关联引擎流程</el-button>
        <el-button type="primary" @click="create">新增或导入</el-button>
      </div>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-else class="surface table-panel">
      <el-table v-loading="loading" :data="items" empty-text="暂无工作流">
        <el-table-column prop="name" label="名称" min-width="170" />
        <el-table-column label="模板" min-width="110"><template #default="{ row }">{{ row.kind === 'echo' ? '文本直通' : '模型对话' }}</template></el-table-column>
        <el-table-column label="操作" min-width="205"><template #default="{ row }">
          <el-button link type="primary" @click="selectItem(row)">详情与执行</el-button>
          <el-button link type="primary" @click="sync(row)">同步</el-button>
          <el-button link type="primary" @click="download(row)">导出</el-button>
        </template></el-table-column>
      </el-table>
    </div>
    <div v-if="chosen" class="surface tool-panel">
      <h2>{{ chosen.name }}</h2><p v-if="chosen.description" class="muted">{{ chosen.description }}</p>
      <p class="muted">版本 {{ history[0]?.number ?? '—' }} · {{ history.map(row => 'V' + row.number + ' ' + new Date(row.created_at).toLocaleDateString('zh-CN')).join(' · ') }}</p>
      <ExecutionPanel :key="chosen.id" :path="'/workflows/' + chosen.id" :needs-model="chosen.kind === 'prompt'" :models="models" />
    </div>
    <el-dialog v-model="editor" :title="mode === 'new' ? '新增或导入工作流' : '关联引擎流程'" width="min(92vw, 560px)">
      <form class="ai-form" @submit.prevent="save">
        <template v-if="mode === 'new'">
          <label class="form-wide">导入已批准模板的 JSON（可选） <input type="file" accept=".json,application/json" @change="readFile" /></label>
          <label class="form-wide">名称 <input v-model="form.name" maxlength="80" required /></label>
          <label class="form-wide">描述 <textarea v-model="form.description" maxlength="1000" rows="2" /></label>
        </template>
        <label v-else class="form-wide">引擎工作流 <select v-model="form.engine_id" required>
          <option disabled value="">选择服务账号可访问的流程</option>
          <option v-for="item in native" :key="item.id" :value="item.id">{{ item.name }} · {{ item.id.slice(0, 8) }}</option>
        </select></label>
        <label class="form-wide">安全模板 <select v-model="form.kind">
          <option value="echo">文本直通</option><option value="prompt">模型对话</option>
        </select></label>
        <div class="form-wide form-actions"><el-button type="primary" native-type="submit" :loading="registering">保存</el-button></div>
      </form>
    </el-dialog>
  </section>
</template>
