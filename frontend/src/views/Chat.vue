<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Plus } from '@element-plus/icons-vue'
import { api, errorMessage } from '../api'
import { isAbort, stream, type Agent, type ModelOption } from '../ai'
import Markdown from '../Markdown.vue'
import ReferenceList from '../ReferenceList.vue'
import type { Reference } from '../resources'

interface Conversation { id: string; title: string; updated_at: string }
interface Message { id: string; role: 'user' | 'assistant'; content: string }

const conversations = ref<Conversation[]>([])
const messages = ref<Message[]>([])
const models = ref<ModelOption[]>([])
const agents = ref<Agent[]>([])
const selected = ref('')
const mode = ref<'model' | 'agent'>('model')
const model = ref('')
const agent = ref('')
const draft = ref('')
const partial = ref('')
const references = ref<Reference[]>([])
const loading = ref(false)
const fetching = ref(false)
const generating = ref(false)
const error = ref('')
const timeline = ref<HTMLElement>()
let generator: AbortController | undefined
let executionId = ''
const targetReady = computed(() => mode.value === 'agent' ? !!agent.value
  : !!model.value || models.value.some(item => item.is_default))
const retryable = computed(() => messages.value.at(-1)?.role === 'user')

async function list() {
  conversations.value = await api<Conversation[]>('/conversations')
}

async function initialize() {
  loading.value = true
  error.value = ''
  try {
    const [, modelRows, agentRows] = await Promise.all([
      list(), api<ModelOption[]>('/models/options'), api<Agent[]>('/agents'),
    ])
    models.value = modelRows
    agents.value = agentRows.filter(item => item.enabled)
    model.value = modelRows.find(item => item.is_default)?.id ?? modelRows[0]?.id ?? ''
    agent.value = agents.value[0]?.id ?? ''
    if (conversations.value[0]) await open(conversations.value[0].id)
  } catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}

async function scrollBottom() {
  await nextTick()
  if (timeline.value) timeline.value.scrollTop = timeline.value.scrollHeight
}

async function open(id: string) {
  if (generating.value) return
  selected.value = id
  references.value = []
  partial.value = ''
  error.value = ''
  messages.value = []
  fetching.value = true
  try {
    const rows = await api<Message[]>('/conversations/' + id + '/messages')
    if (selected.value === id) messages.value = rows
    void scrollBottom()
  } catch (cause) {
    if (selected.value === id) error.value = errorMessage(cause)
  } finally {
    if (selected.value === id) fetching.value = false
  }
}

async function create() {
  const row = await api<Conversation>('/conversations', 'POST', { title: '新对话' })
  conversations.value.unshift(row)
  selected.value = row.id
  messages.value = []
  partial.value = ''
  return row
}

async function newChat() {
  if (generating.value) return
  error.value = ''
  try { await create() } catch (cause) { error.value = errorMessage(cause) }
}

async function rename(row: Conversation) {
  if (generating.value) return
  let title: string
  try {
    const answer = await ElMessageBox.prompt('输入会话名称', '重命名', {
      inputValue: row.title, inputValidator: value => !!value?.trim() && value.trim().length <= 80,
    })
    title = answer.value
  } catch { return }
  try {
    await api('/conversations/' + row.id, 'PATCH', { title: title.trim() })
    await list()
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}

async function remove(row: Conversation) {
  if (generating.value) return
  try { await ElMessageBox.confirm('删除会话「' + row.title + '」和其中的消息？', '删除会话', { type: 'warning' }) }
  catch { return }
  try {
    await api('/conversations/' + row.id, 'DELETE')
    if (selected.value === row.id) {
      selected.value = ''
      messages.value = []
    }
    await list()
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}

async function send(retry = false) {
  const input = draft.value.trim()
  if (generating.value || fetching.value || !targetReady.value || (!retry && !input)) return
  generating.value = true
  executionId = ''
  references.value = []
  error.value = ''
  partial.value = ''
  let id = selected.value
  let optimistic = ''
  try {
    if (!id) id = (await create()).id
    if (!retry) {
      optimistic = 'local-' + Date.now()
      messages.value.push({ id: optimistic, role: 'user', content: input })
      draft.value = ''
    }
    await scrollBottom()
    generator = new AbortController()
    const target = mode.value === 'agent' ? { agent_id: agent.value } : { model_id: model.value || null }
    await stream('/conversations/' + id + '/generate', { ...target, text: retry ? '' : input, retry },
      generator.signal, chunk => {
        partial.value += chunk
        const panel = timeline.value
        if (panel && panel.scrollHeight - panel.scrollTop - panel.clientHeight < 120) void scrollBottom()
      }, (id, sources) => { executionId = id; references.value = sources })
  } catch (cause) {
    error.value = isAbort(cause) ? '已停止生成，可重试最后一条消息。' : errorMessage(cause)
  } finally {
    generating.value = false
    if (id && selected.value === id) {
      try {
        messages.value = await api<Message[]>('/conversations/' + id + '/messages')
        if (optimistic && messages.value.at(-1)?.content !== input &&
          !messages.value.some(message => message.role === 'user' && message.content === input) && error.value) draft.value = input
        await list()
      } catch (cause) { if (!error.value) error.value = errorMessage(cause) }
      if (!error.value) partial.value = ''
    }
  }
}

async function stop() {
  try {
    if (executionId) await api('/executions/' + executionId + '/stop', 'POST')
    else generator?.abort()
  } catch { generator?.abort() }
}

function enter(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void send()
}

async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); ElMessage.success('消息已复制') }
  catch { ElMessage.error('剪贴板不可用') }
}

onMounted(initialize)
onUnmounted(() => generator?.abort())
</script>

<template>
  <section class="chat-page">
    <div class="page-heading"><div><h1>AI 对话</h1><p class="muted">选择模型或智能体，开始多轮对话。</p></div>
      <el-button :icon="Plus" type="primary" :disabled="generating" @click="newChat">新建会话</el-button>
    </div>
    <el-skeleton v-if="loading" :rows="5" animated />
    <div v-else class="surface chat-layout">
      <aside class="chat-sidebar" aria-label="历史会话">
        <h2>历史会话</h2>
        <p v-if="!conversations.length" class="muted">暂无会话</p>
        <div v-for="row in conversations" :key="row.id" class="history-row" :class="{ 'history-current': selected === row.id }">
          <button class="history-title" :disabled="generating" :title="row.title" @click="open(row.id)">{{ row.title }}</button>
          <el-dropdown trigger="click" @command="(action: string) => action === 'rename' ? rename(row) : remove(row)">
            <el-button text aria-label="会话操作" :disabled="generating">···</el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item command="rename">重命名</el-dropdown-item>
              <el-dropdown-item command="delete">删除</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </aside>
      <div class="chat-main">
        <div class="chat-target">
          <select v-model="mode" aria-label="对话类型" :disabled="generating">
            <option value="model">模型对话</option><option value="agent">智能体对话</option>
          </select>
          <select v-if="mode === 'model'" v-model="model" aria-label="模型" :disabled="generating">
            <option v-if="!models.length" value="">暂无启用模型</option>
            <option v-for="item in models" :key="item.id" :value="item.id">{{ item.name }}{{ item.is_default ? ' · 默认' : '' }}</option>
          </select>
          <select v-else v-model="agent" aria-label="智能体" :disabled="generating">
            <option v-if="!agents.length" value="">暂无可用智能体</option>
            <option v-for="item in agents" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
        </div>
        <div ref="timeline" class="chat-timeline" aria-label="消息">
          <el-skeleton v-if="fetching" :rows="4" animated />
          <div v-else-if="!messages.length && !generating" class="chat-empty">
            <span class="service-icon"><el-icon><ChatDotRound /></el-icon></span>
            <h2>开始对话</h2>
            <p class="muted">{{ targetReady ? '发送消息开始。' : '请选择已启用的模型或智能体。' }}</p>
          </div>
          <template v-else>
            <article v-for="message in messages" :key="message.id" class="chat-message" :class="'chat-' + message.role">
              <div class="message-label">{{ message.role === 'user' ? '你' : '助手' }}</div>
              <div v-if="message.role === 'user'" class="user-message">{{ message.content }}</div>
              <Markdown v-else :text="message.content" />
              <el-button text size="small" @click="copy(message.content)">复制消息</el-button>
            </article>
            <article v-if="generating || partial" class="chat-message chat-assistant" aria-live="polite">
              <div class="message-label">{{ generating ? '助手 · 生成中' : '助手 · 未完成' }}</div>
              <Markdown v-if="partial" :text="partial" /><p v-else class="muted">等待模型响应…</p>
            </article>
          </template>
          <ReferenceList :items="references" />
        </div>
        <form class="chat-composer" @submit.prevent="send()">
          <el-alert v-if="error" :title="error" type="error" :closable="false" />
          <textarea v-model="draft" rows="3" maxlength="12000" placeholder="输入消息，Shift + Enter 换行" aria-label="消息内容" @keydown="enter" />
          <div class="inline-actions chat-send">
            <el-button v-if="retryable && !generating" :disabled="!targetReady" @click="send(true)">重试生成</el-button>
            <el-button v-if="generating" @click="stop">停止生成</el-button>
            <el-button v-else type="primary" native-type="submit" :disabled="!draft.trim() || !targetReady || fetching">发送</el-button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>
