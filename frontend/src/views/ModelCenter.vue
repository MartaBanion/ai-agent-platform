<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../api'
import type { Execution, Model } from '../ai'

const models = ref<Model[]>([])
const error = ref('')
const loading = ref(false)
const editor = ref(false)
const selected = ref<Model | null>(null)
const saving = ref(false)
const testing = ref('')
const stats = ref<Record<string, number | null> | null>(null)
const statsName = ref('')
const statsOpen = ref(false)
const recentCalls = ref<Execution[]>([])
const providers: Record<string, string> = { openai: 'OpenAI', deepseek: 'DeepSeek', qwen: 'Qwen', custom: '自定义' }
const defaults = { name: '', provider: 'openai', base_url: '', model: '', api_key: '',
  temperature: 0.3, max_tokens: 1024, timeout: 45, enabled: true, is_default: false, clear_key: false }
const form = reactive({ ...defaults })

async function load() {
  loading.value = true
  error.value = ''
  try {
    models.value = await api<Model[]>('/models')
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    loading.value = false
  }
}

function edit(model: Model | null) {
  selected.value = model
  Object.assign(form, defaults)
  if (model) {
    const { name, provider, base_url, model: identifier, temperature, max_tokens, timeout, enabled, is_default } = model
    Object.assign(form, { name, provider, base_url, model: identifier, temperature, max_tokens, timeout, enabled, is_default })
  }
  editor.value = true
}

async function save() {
  saving.value = true
  try {
    const data = { ...form, base_url: form.provider === 'custom' ? form.base_url : '',
      api_key: form.api_key || null, is_default: form.enabled && form.is_default }
    await api('/models' + (selected.value ? '/' + selected.value.id : ''), selected.value ? 'PUT' : 'POST', data)
    editor.value = false
    await load()
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  } finally {
    saving.value = false
  }
}

async function remove(model: Model) {
  try {
    await ElMessageBox.confirm('确定删除模型「' + model.name + '」？', '删除模型', { type: 'warning' })
  } catch { return }
  try {
    await api('/models/' + model.id, 'DELETE')
    await load()
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}

async function probe(model: Model) {
  testing.value = model.id
  try {
    const result = await api<{ duration_ms: number }>('/models/' + model.id + '/test', 'POST', undefined, 105000)
    ElMessage.success('连接成功 · ' + result.duration_ms + ' 毫秒')
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
  finally { testing.value = '' }
}

async function usage(model: Model) {
  try {
    [stats.value, recentCalls.value] = await Promise.all([
      api<Record<string, number | null>>('/models/' + model.id + '/usage'),
      api<Execution[]>('/models/' + model.id + '/history'),
    ])
    statsName.value = model.name
    statsOpen.value = true
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}

const fields = { calls: '调用次数', success: '成功次数', avg_ms: '平均耗时（毫秒）',
  input_tokens: '输入 Token', output_tokens: '输出 Token', total_tokens: '总 Token' }
const runStatus: Record<string, string> = { success: '成功', failed: '失败', running: '运行中', cancelled: '已取消' }

onMounted(load)
</script>

<template>
  <section>
    <div class="page-heading"><div><h1>模型管理</h1><p class="muted">配置云端模型、测试连接和查看调用统计。</p></div>
      <el-button type="primary" @click="edit(null)">新增模型</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-else class="surface table-panel">
      <el-table v-loading="loading" :data="models" empty-text="暂无模型，请新增云端模型配置">
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="服务商" min-width="100"><template #default="{ row }">{{ providers[row.provider] }}</template></el-table-column>
        <el-table-column prop="model" label="模型标识" min-width="155" />
        <el-table-column label="状态" min-width="120"><template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          <span v-if="row.is_default" class="inline-label">默认</span>
        </template></el-table-column>
        <el-table-column label="操作" min-width="270"><template #default="{ row }">
          <el-button link type="primary" :loading="testing === row.id" :disabled="!!testing" @click="probe(row)">测试连接</el-button>
          <el-button link type="primary" @click="usage(row)">统计</el-button>
          <el-button link type="primary" @click="edit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template></el-table-column>
      </el-table>
    </div>
    <el-dialog v-model="editor" :title="selected ? '编辑模型' : '新增模型'" width="min(92vw, 620px)" @closed="form.api_key = ''">
      <form class="ai-form" @submit.prevent="save">
        <label>显示名称 <input v-model="form.name" maxlength="80" required /></label>
        <label>服务商 <select v-model="form.provider"><option v-for="(label, id) in providers" :key="id" :value="id">{{ label }}</option></select></label>
        <label v-if="form.provider === 'custom'" class="form-wide">Base URL <input v-model="form.base_url" placeholder="https://api.example.com/v1" maxlength="320" required /></label>
        <label class="form-wide">模型标识 <input v-model="form.model" maxlength="160" required /></label>
        <label class="form-wide">API Key <input v-model="form.api_key" type="password" autocomplete="new-password" :placeholder="selected?.has_key ? '已加密配置，留空以保留' : '从服务商控制台复制'" maxlength="1024" /></label>
        <label v-if="selected?.has_key" class="check-label form-wide"><input v-model="form.clear_key" type="checkbox" /> 清除已有 API Key</label>
        <label>Temperature <input v-model.number="form.temperature" type="number" min="0" max="2" step="0.01" required /></label>
        <label>Max Tokens <input v-model.number="form.max_tokens" type="number" min="1" max="8192" required /></label>
        <label>超时（秒） <input v-model.number="form.timeout" type="number" min="5" max="90" required /></label>
        <div class="form-wide inline-actions"><label class="check-label"><input v-model="form.enabled" type="checkbox" /> 启用</label>
          <label class="check-label"><input v-model="form.is_default" type="checkbox" :disabled="!form.enabled" /> 设为默认</label>
        </div>
        <div class="form-wide form-actions"><el-button type="primary" native-type="submit" :loading="saving">保存</el-button></div>
      </form>
    </el-dialog>
    <el-dialog v-model="statsOpen" :title="statsName + ' · 调用统计'" width="min(92vw, 740px)">
      <el-descriptions v-if="stats" :column="1">
        <el-descriptions-item v-for="(label, key) in fields" :key="key" :label="label">
          {{ stats[key] == null ? '暂无上游数据' : Math.round(Number(stats[key])).toLocaleString() }}
        </el-descriptions-item>
      </el-descriptions>
      <p class="muted">Token 仅汇总上游实际返回数值。</p>
      <div class="section-heading"><h2>最近调用</h2></div>
      <el-table :data="recentCalls" empty-text="暂无调用">
        <el-table-column label="时间" min-width="155"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template></el-table-column>
        <el-table-column label="状态" min-width="80"><template #default="{ row }">{{ runStatus[row.status] }}</template></el-table-column>
        <el-table-column label="耗时" min-width="85"><template #default="{ row }">{{ row.duration_ms == null ? '—' : row.duration_ms + ' ms' }}</template></el-table-column>
        <el-table-column label="Token" min-width="85"><template #default="{ row }">{{ row.total_tokens ?? '—' }}</template></el-table-column>
        <el-table-column prop="error" label="失败原因" min-width="140" />
      </el-table>
    </el-dialog>
  </section>
</template>
