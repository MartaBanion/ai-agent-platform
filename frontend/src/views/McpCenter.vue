<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import type { Agent } from '../ai'
import { callStates, type Server, type Tool, type ToolCall } from '../resources'

const auth = useAuth()
const admin = computed(() => auth.user?.role === 'admin')
const servers = ref<Server[]>([])
const logs = ref<ToolCall[]>([])
const agents = ref<Agent[]>([])
const agent = ref('')
const selected = ref<Server | null>(null)
const error = ref('')
const loading = ref(false)
const checking = ref(false)
const saving = ref(false)
const editor = ref(false)
const editId = ref('')
const dialog = ref(false)
const tool = ref<Tool>()
const target = ref<Server>()
const args = ref('{}')
const debugError = ref('')
const busy = ref(false)
const receipt = ref<ToolCall>()
const receiptOpen = ref(false)
const defaults = { name: '', kind: 'builtin' as Server['kind'], url: '', api_key: '', clear_key: false,
  enabled: true, shared: false, approval: true, allowed: [] as string[] }
const form = reactive({ ...defaults })
const editing = ref<Server>()

async function list() {
  loading.value = true
  error.value = ''
  try {
    const query = agent.value ? '?agent_id=' + agent.value : ''
    const data = await api<Server[]>('/mcp/servers' + query)
    servers.value = data
    selected.value = data.find(row => row.id === selected.value?.id) ?? data[0] ?? null
  } catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}

async function loadLogs() {
  try { logs.value = await api('/mcp/calls') }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
}

function edit(server?: Server) {
  editing.value = server
  editId.value = server?.id ?? ''
  Object.assign(form, defaults, { allowed: [] })
  if (server) {
    const { name, kind, url, enabled, shared, approval, allowed } = server
    Object.assign(form, { name, kind, url: url ?? '', enabled, shared, approval, allowed: [...allowed] })
  }
  editor.value = true
}

async function save() {
  saving.value = true
  try {
    const data = { ...form, api_key: form.api_key || null }
    const path = '/mcp/servers' + (editId.value ? '/' + editId.value : '')
    const value = await api<Server>(path, editId.value ? 'PUT' : 'POST', data)
    editor.value = false
    await list()
    selected.value = servers.value.find(row => row.id === value.id) ?? selected.value
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
  finally { saving.value = false }
}

async function discover(server: Server) {
  checking.value = true
  try {
    const result = await api<Server>('/mcp/servers/' + server.id + '/test', 'POST', undefined, 16000)
    await list()
    ElMessage.success('MCP 连接成功，发现 ' + result.tools.length + ' 个工具')
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
  finally { checking.value = false }
}

async function remove(server: Server) {
  try { await ElMessageBox.confirm('删除 MCP 服务「' + server.name + '」？', '删除服务', { type: 'warning' }) }
  catch { return }
  try { await api('/mcp/servers/' + server.id, 'DELETE'); await list(); await loadLogs() }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
}

function debug(server: Server, entry: Tool) {
  tool.value = entry
  target.value = server
  args.value = '{}'
  debugError.value = ''
  dialog.value = true
}

async function submit() {
  if (!tool.value || !target.value) return
  debugError.value = ''
  let parsed: unknown
  try {
    parsed = JSON.parse(args.value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
  } catch {
    debugError.value = '工具参数须为 JSON 对象'
    return
  }
  busy.value = true
  try {
    const row = await api<ToolCall>('/mcp/servers/' + target.value.id + '/calls', 'POST',
      { tool: tool.value.name, arguments: parsed, agent_id: agent.value || null }, 16000)
    dialog.value = false
    showReceipt(row)
    await loadLogs()
  } catch (cause) { debugError.value = errorMessage(cause) }
  finally { busy.value = false }
}

function showReceipt(row: ToolCall) {
  receipt.value = row
  receiptOpen.value = true
}

async function review(row: ToolCall, approve: boolean) {
  busy.value = true
  try {
    const result = await api<ToolCall>('/mcp/calls/' + row.id + '/review', 'POST', { approve }, 16000)
    showReceipt(result)
    await loadLogs()
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
  finally { busy.value = false }
}

watch(agent, () => void list())
onMounted(async () => {
  await Promise.all([list(), loadLogs()])
  try { agents.value = (await api<Agent[]>('/agents')).filter(item => item.enabled) }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
})
</script>

<template>
  <section>
    <div class="page-heading">
      <div><h1>MCP 工具中心</h1><p class="muted">管理服务、审核工具并查看真实调用结果。</p></div>
      <el-button v-if="admin" type="primary" @click="edit()">注册服务</el-button>
    </div>
    <div class="inline-actions tool-filter">
      <label for="mcp-agent">调用身份</label>
      <select id="mcp-agent" v-model="agent">
        <option value="">直接调试</option><option v-for="item in agents" :key="item.id" :value="item.id">智能体 · {{ item.name }}</option>
      </select>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-skeleton v-else-if="loading && !servers.length" :rows="4" animated />
    <el-empty v-else-if="!servers.length" description="暂无可访问的 MCP 服务" />
    <div v-else class="resource-layout">
      <aside class="surface resource-menu" aria-label="MCP 服务">
        <button v-for="server in servers" :key="server.id" :class="{ active: selected?.id === server.id }" @click="selected = server">
          <strong>{{ server.name }}</strong><span class="muted">{{ server.kind === 'builtin' ? '内置' : '外部' }} · {{ server.enabled ? '启用' : '停用' }}</span>
        </button>
      </aside>
      <div v-if="selected" class="surface resource-detail">
        <div class="section-heading resource-title">
          <div><h2>{{ selected.name }}</h2><p class="muted">Streamable HTTP · {{ selected.approval ? '调用需审批' : '直接调用' }}</p></div>
          <div v-if="admin && !agent" class="inline-actions">
            <el-button :loading="checking" @click="discover(selected)">连接测试与发现</el-button>
            <el-button @click="edit(selected)">编辑</el-button>
            <el-button type="danger" plain @click="remove(selected)">删除</el-button>
          </div>
        </div>
        <el-table :data="selected.tools" empty-text="暂无已发现或授权的工具">
          <el-table-column prop="name" label="工具" min-width="145" />
          <el-table-column prop="description" label="说明" min-width="190" show-overflow-tooltip />
          <el-table-column label="授权" min-width="85"><template #default="{ row }">
            <el-tag :type="selected?.allowed.includes(row.name) ? 'success' : 'info'">
              {{ selected?.allowed.includes(row.name) ? '已授权' : '未授权' }}
            </el-tag>
          </template></el-table-column>
          <el-table-column label="操作" min-width="100"><template #default="{ row }">
            <el-button link type="primary" @click="selected && debug(selected, row)">参数与调试</el-button>
          </template></el-table-column>
        </el-table>
      </div>
    </div>
    <div class="section-heading"><h2>调用和审批记录</h2><el-button text @click="loadLogs">刷新记录</el-button></div>
    <div class="surface table-panel">
      <el-table :data="logs" empty-text="暂无调用">
        <el-table-column prop="name" label="工具" min-width="135" />
        <el-table-column label="状态" min-width="85"><template #default="{ row }">
          <el-tag :type="row.state === 'success' ? 'success' : row.state === 'failed' ? 'danger' : 'info'">{{ callStates[row.state] }}</el-tag>
        </template></el-table-column>
        <el-table-column label="时间" min-width="150"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template></el-table-column>
        <el-table-column label="耗时" min-width="75"><template #default="{ row }">{{ row.duration_ms == null ? '—' : row.duration_ms + ' ms' }}</template></el-table-column>
        <el-table-column label="操作" min-width="125"><template #default="{ row }">
          <el-button link type="primary" @click="showReceipt(row)">{{ row.state === 'pending' && admin ? '查看并审批' : '查看' }}</el-button>
        </template></el-table-column>
      </el-table>
    </div>
    <el-dialog v-model="editor" :title="editId ? '编辑 MCP 服务' : '注册 MCP 服务'" width="min(92vw, 640px)" @closed="form.api_key = ''">
      <form class="ai-form" @submit.prevent="save">
        <label>名称 <input v-model="form.name" maxlength="80" required /></label>
        <label>服务类型 <select v-model="form.kind"><option value="builtin">内置企业运维</option><option value="external">外部 Streamable HTTP</option></select></label>
        <template v-if="form.kind === 'external'">
          <label class="form-wide">HTTPS 地址 <input v-model="form.url" placeholder="https://tools.example.com/mcp" maxlength="320" required /></label>
          <label class="form-wide">Bearer API Key <input v-model="form.api_key" type="password" autocomplete="new-password" :placeholder="editing?.has_key ? '已加密配置，留空保留' : '可选'" /></label>
          <label v-if="editing?.has_key" class="check-label form-wide"><input v-model="form.clear_key" type="checkbox" /> 清除旧密钥</label>
        </template>
        <div class="form-wide inline-actions">
          <label class="check-label"><input v-model="form.enabled" type="checkbox" /> 启用</label>
          <label class="check-label"><input v-model="form.shared" type="checkbox" /> 向登录用户共享</label>
          <label v-if="form.kind === 'builtin'" class="check-label"><input v-model="form.approval" type="checkbox" /> 每次调用需审批</label>
          <span v-else class="muted">外部工具每次调用需审批</span>
        </div>
        <div v-if="editing?.tools.length" class="form-wide tool-checks"><h2>授权工具</h2>
          <label v-for="item in editing.tools" :key="item.name" class="check-label">
            <input v-model="form.allowed" type="checkbox" :value="item.name" /> {{ item.name }}
          </label>
        </div>
        <div class="form-wide form-actions"><el-button type="primary" native-type="submit" :loading="saving">保存</el-button></div>
      </form>
    </el-dialog>
    <el-dialog v-model="dialog" :title="tool?.name + ' · 参数与调试'" width="min(92vw, 680px)">
      <p v-if="tool" class="muted">{{ tool.description }}</p>
      <pre class="structured-output">{{ JSON.stringify(tool?.schema, null, 2) }}</pre>
      <el-alert v-if="debugError" :title="debugError" type="error" :closable="false" />
      <form class="ai-form" @submit.prevent="submit">
        <label class="form-wide">工具参数（JSON） <textarea v-model="args" rows="4" /></label>
        <div class="form-wide form-actions"><el-button type="primary" native-type="submit" :loading="busy"
          :disabled="!target?.enabled || !tool || !target.allowed.includes(tool.name)">
          {{ target?.approval ? '提交审批' : '调用工具' }}
        </el-button></div>
      </form>
    </el-dialog>
    <el-dialog v-model="receiptOpen" :title="receipt?.name + ' · 调用记录'" width="min(92vw, 680px)">
      <template v-if="receipt">
        <p class="muted">{{ callStates[receipt.state] }}{{ receipt.duration_ms == null ? '' : ' · ' + receipt.duration_ms + ' 毫秒' }}</p>
        <el-alert v-if="receipt.error" :title="receipt.error" type="error" :closable="false" />
        <pre v-if="receipt.result || receipt.arguments" class="structured-output">{{ JSON.stringify(receipt.result ?? receipt.arguments, null, 2) }}</pre>
        <div v-if="admin && receipt.state === 'pending'" class="inline-actions">
          <el-button type="primary" :loading="busy" @click="review(receipt, true)">批准并执行</el-button>
          <el-button type="danger" plain :disabled="busy" @click="review(receipt, false)">拒绝</el-button>
        </div>
      </template>
    </el-dialog>
  </section>
</template>
