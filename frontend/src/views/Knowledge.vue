<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import type { Knowledge, Reference } from '../resources'
import ReferenceList from '../ReferenceList.vue'

interface Document { id: string; name: string; format: string; size: number; status: string; error: string | null }
interface Passage { number: number; page: number | null; text: string }
const auth = useAuth()
const builder = computed(() => auth.user?.role === 'admin' || auth.user?.role === 'developer')
const items = ref<Knowledge[]>([])
const selected = ref<Knowledge | null>(null)
const docs = ref<Document[]>([])
const editor = ref(false)
const editing = ref(false)
const saving = ref(false)
const loading = ref(false)
const uploading = ref(false)
const error = ref('')
const detailError = ref('')
const fileInput = ref<HTMLInputElement>()
const file = ref<File>()
const preview = ref<Document>()
const chunks = ref<Passage[]>([])
const offset = ref(0)
const previewOpen = ref(false)
const previewLoading = ref(false)
const searching = ref(false)
const searched = ref(false)
const hits = ref<Reference[]>([])
const query = reactive({ text: '', top_k: 4, threshold: 0.45 })
const defaults = { name: '', description: '', enabled: true, shared: false, embedding: 'local',
  chunk_size: 320, overlap: 40, top_k: 4, threshold: 0.45 }
const form = reactive({ ...defaults })
const labels: Record<string, string> = { queued: '排队', processing: '处理中', ready: '可检索', failed: '失败' }
let timer: number | undefined
let readingDocs = false

async function list() {
  loading.value = true
  try {
    items.value = await api('/knowledge')
    if (selected.value) selected.value = items.value.find(row => row.id === selected.value?.id) ?? null
  } catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}

async function listDocs() {
  const key = selected.value?.id
  if (!key || readingDocs) return
  readingDocs = true
  try {
    const data = await api<Document[]>('/knowledge/' + key + '/documents')
    if (selected.value?.id === key) docs.value = data
  } catch (cause) { if (selected.value?.id === key) detailError.value = errorMessage(cause) }
  finally {
    readingDocs = false
    if (selected.value && selected.value.id !== key) void listDocs()
  }
}

function choose(row: Knowledge) {
  selected.value = row
  docs.value = []
  hits.value = []
  detailError.value = ''
  searched.value = false
  file.value = undefined
  if (fileInput.value) fileInput.value.value = ''
  Object.assign(query, { text: '', top_k: row.top_k, threshold: row.threshold })
  void listDocs()
}

function edit(row: Knowledge | null) {
  editing.value = !!row
  Object.assign(form, defaults)
  if (row) {
    const { name, description, enabled, shared, embedding, chunk_size, overlap, top_k, threshold } = row
    Object.assign(form, { name, description, enabled, shared, embedding, chunk_size, overlap, top_k, threshold })
  }
  editor.value = true
}

async function save() {
  saving.value = true
  try {
    const { embedding, ...body } = form
    const row = editing.value && selected.value
      ? await api<Knowledge>('/knowledge/' + selected.value.id, 'PUT', body)
      : await api<Knowledge>('/knowledge', 'POST', { ...body, embedding })
    editor.value = false
    await list()
    choose(row)
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
  finally { saving.value = false }
}

async function remove() {
  const row = selected.value
  if (!row) return
  try { await ElMessageBox.confirm('删除知识库及其全部文档和向量？', '删除知识库', { type: 'warning' }) }
  catch { return }
  try {
    await api('/knowledge/' + row.id, 'DELETE')
    if (selected.value?.id === row.id) selected.value = null
    await list()
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}

function selectFile(event: Event) {
  const entry = (event.target as HTMLInputElement).files?.[0]
  if (entry && entry.size > 8 * 1024 * 1024) {
    ElMessage.error('文件不得超过 8 MiB')
    file.value = undefined
  } else file.value = entry
}

async function upload() {
  if (!selected.value || !file.value) return
  uploading.value = true
  const body = new FormData()
  body.append('file', file.value)
  try {
    await api('/knowledge/' + selected.value.id + '/documents', 'POST', body, 30000)
    ElMessage.success('文档已进入处理队列')
    file.value = undefined
    if (fileInput.value) fileInput.value.value = ''
    await listDocs()
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
  finally { uploading.value = false }
}

function path(doc: Document) { return '/knowledge/' + selected.value?.id + '/documents/' + doc.id }

async function selectPreview(doc: Document, start = 0) {
  preview.value = doc
  previewOpen.value = true
  previewLoading.value = true
  try {
    chunks.value = await api(path(doc) + '/passages?offset=' + start)
    offset.value = start
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
  finally { previewLoading.value = false }
}

async function process(doc: Document) {
  try { await api(path(doc) + '/reprocess', 'POST'); await listDocs() }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
}

async function removeDoc(doc: Document) {
  try { await ElMessageBox.confirm('删除文档及其向量？', '删除文档', { type: 'warning' }) }
  catch { return }
  try { await api(path(doc), 'DELETE'); hits.value = []; searched.value = false; await listDocs() }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
}

async function search() {
  const key = selected.value?.id
  if (!key || !query.text.trim()) return
  searching.value = true
  searched.value = false
  hits.value = []
  detailError.value = ''
  try {
    const data = await api<Reference[]>('/knowledge/' + key + '/search', 'POST', { ...query }, 35000)
    if (selected.value?.id === key) { hits.value = data; searched.value = true }
  } catch (cause) { if (selected.value?.id === key) detailError.value = errorMessage(cause) }
  finally { searching.value = false }
}

onMounted(() => {
  void list()
  timer = window.setInterval(() => {
    if (docs.value.some(doc => ['queued', 'processing'].includes(doc.status))) void listDocs()
  }, 1500)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <section>
    <div class="page-heading">
      <div><h1>知识库管理</h1><p class="muted">管理文档、查看索引状态并验证语义检索。</p></div>
      <el-button v-if="builder" type="primary" @click="edit(null)">新建知识库</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-skeleton v-else-if="loading && !items.length" :rows="4" animated />
    <el-empty v-else-if="!items.length" description="暂无可访问的知识库" />
    <div v-else class="resource-layout">
      <aside class="surface resource-menu" aria-label="知识库列表">
        <button v-for="row in items" :key="row.id" :class="{ active: selected?.id === row.id }" @click="choose(row)">
          <strong>{{ row.name }}</strong><span class="muted">{{ row.enabled ? '已启用' : '已停用' }} · {{ row.shared ? '共享' : '私有' }}</span>
        </button>
      </aside>
      <div v-if="selected" class="surface resource-detail">
        <div class="section-heading resource-title">
          <div><h2>{{ selected.name }}</h2><p v-if="selected.description" class="muted">{{ selected.description }}</p></div>
          <div v-if="selected.editable" class="inline-actions">
            <el-button @click="edit(selected)">编辑</el-button><el-button type="danger" plain @click="remove">删除</el-button>
          </div>
        </div>
        <p class="muted resource-profile">{{ selected.profile }} · {{ selected.dimension }} 维</p>
        <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
        <div class="section-heading"><h2>文档</h2><el-button text @click="listDocs">刷新</el-button></div>
        <form v-if="selected.editable" class="inline-actions upload-row" @submit.prevent="upload">
          <input ref="fileInput" type="file" aria-label="选择文档" accept=".pdf,.docx,.txt,.md,.markdown" @change="selectFile">
          <el-button type="primary" native-type="submit" :disabled="!file" :loading="uploading">上传文档</el-button>
          <span class="muted">PDF、DOCX、TXT、Markdown · 每份 8 MiB</span>
        </form>
        <el-table :data="docs" empty-text="暂无文档">
          <el-table-column prop="name" label="文档" min-width="145" />
          <el-table-column label="状态" min-width="92"><template #default="{ row }">
            <el-tag :type="row.status === 'ready' ? 'success' : row.status === 'failed' ? 'danger' : 'info'">{{ labels[row.status] }}</el-tag>
          </template></el-table-column>
          <el-table-column prop="error" label="失败原因" min-width="110" show-overflow-tooltip />
          <el-table-column label="操作" min-width="205"><template #default="{ row }">
            <a :href="'/api/v1' + path(row) + '/download'">下载</a>
            <el-button v-if="row.status === 'ready'" link type="primary" @click="selectPreview(row)">片段</el-button>
            <template v-if="selected?.editable">
              <el-button link type="primary" :disabled="['queued', 'processing'].includes(row.status)" @click="process(row)">重处理</el-button>
              <el-button link type="danger" :disabled="['queued', 'processing'].includes(row.status)" @click="removeDoc(row)">删除</el-button>
            </template>
          </template></el-table-column>
        </el-table>
        <div class="section-heading"><h2>检索测试</h2></div>
        <form class="ai-form" @submit.prevent="search">
          <label class="form-wide">检索问题 <textarea v-model="query.text" rows="2" maxlength="1600" required /></label>
          <label>Top K <input v-model.number="query.top_k" type="number" min="1" max="10" required /></label>
          <label>相似度阈值 <input v-model.number="query.threshold" type="number" min="0" max="1" step="0.01" required /></label>
          <div class="form-wide inline-actions"><el-button type="primary" native-type="submit" :disabled="!selected.enabled" :loading="searching">执行检索</el-button>
            <span v-if="!selected.enabled" class="muted">知识库已停用</span></div>
        </form>
        <el-empty v-if="searched && !hits.length" description="未找到达到阈值的片段" />
        <ReferenceList :items="hits" />
      </div>
      <el-empty v-else description="选择一个知识库以管理文档" />
    </div>
    <el-dialog v-model="editor" :title="editing ? '编辑知识库' : '新建知识库'" width="min(92vw, 620px)">
      <form class="ai-form" @submit.prevent="save">
        <label class="form-wide">名称 <input v-model="form.name" maxlength="80" required /></label>
        <label class="form-wide">描述 <textarea v-model="form.description" rows="2" maxlength="1000" /></label>
        <label class="form-wide">Embedding <select v-model="form.embedding" :disabled="editing">
          <option value="local">本地多语言 E5-small</option><option value="cloud">云端（需要部署配置）</option>
        </select></label>
        <label>切分长度 <input v-model.number="form.chunk_size" type="number" min="100" max="480" required /></label>
        <label>重叠字符 <input v-model.number="form.overlap" type="number" min="0" max="120" required /></label>
        <label>默认 Top K <input v-model.number="form.top_k" type="number" min="1" max="10" required /></label>
        <label>默认相关度阈值 <input v-model.number="form.threshold" type="number" min="0" max="1" step="0.01" required /></label>
        <div class="form-wide inline-actions">
          <label class="check-label"><input v-model="form.enabled" type="checkbox" /> 启用</label>
          <label class="check-label"><input v-model="form.shared" type="checkbox" /> 向登录用户共享</label>
        </div>
        <div class="form-wide form-actions"><el-button type="primary" native-type="submit" :loading="saving">保存</el-button></div>
      </form>
    </el-dialog>
    <el-dialog v-model="previewOpen" :title="preview?.name + ' · 片段'" width="min(92vw, 720px)">
      <div v-loading="previewLoading" class="references">
        <el-empty v-if="!chunks.length" description="没有可预览片段" />
        <article v-for="chunk in chunks" :key="chunk.number" class="surface reference-card">
          <strong>片段 {{ chunk.number }}{{ chunk.page ? ' · 第 ' + chunk.page + ' 页' : '' }}</strong><p>{{ chunk.text }}</p>
        </article>
      </div>
      <div v-if="preview" class="inline-actions panel-gap">
        <el-button :disabled="offset === 0" @click="selectPreview(preview, offset - 50)">上一页</el-button>
        <el-button :disabled="chunks.length < 50" @click="selectPreview(preview, offset + 50)">下一页</el-button>
      </div>
    </el-dialog>
  </section>
</template>
