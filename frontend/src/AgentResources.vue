<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from './api'
import type { Knowledge, Server } from './resources'

const props = defineProps<{ agentId: string }>()
const emit = defineEmits<{ saved: [] }>()
type Grant = { server_id: string; name: string }
interface Links { knowledge_ids: string[]; tools: Grant[] }
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const libraries = ref<Knowledge[]>([])
const tools = ref<{ key: string; label: string; grant: Grant }[]>([])
const selectedKnowledge = ref<string[]>([])
const selectedTools = ref<string[]>([])
const toolKey = (row: Grant) => row.server_id + ':' + row.name

async function load() {
  if (!props.agentId) return
  loading.value = true
  error.value = ''
  try {
    const [available, mcp, current] = await Promise.all([
      api<Knowledge[]>('/knowledge'), api<Server[]>('/mcp/servers'),
      api<Links>('/agents/' + props.agentId + '/resources'),
    ])
    libraries.value = available
    tools.value = mcp.filter(server => server.enabled).flatMap(server =>
      server.tools.filter(tool => server.allowed.includes(tool.name)).map(tool => {
        const grant = { server_id: server.id, name: tool.name }
        return { key: toolKey(grant), label: server.name + ' · ' + tool.name, grant }
      }))
    selectedKnowledge.value = current.knowledge_ids.filter(key => available.some(row => row.id === key))
    selectedTools.value = current.tools.map(toolKey).filter(key => tools.value.some(row => row.key === key))
  } catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}

async function save() {
  saving.value = true
  try {
    await api('/agents/' + props.agentId + '/resources', 'PUT', {
      knowledge_ids: selectedKnowledge.value,
      tools: tools.value.filter(row => selectedTools.value.includes(row.key)).map(row => row.grant),
    })
    ElMessage.success('资源授权已保存')
    emit('saved')
  } catch (cause) { error.value = errorMessage(cause) }
  finally { saving.value = false }
}

watch(() => props.agentId, load, { immediate: true })
</script>

<template>
  <el-skeleton v-if="loading" :rows="3" animated />
  <form v-else class="ai-form" @submit.prevent="save">
    <el-alert v-if="error" class="form-wide" :title="error" type="error" :closable="false" />
    <div class="form-wide tool-checks">
      <h2>知识库</h2>
      <p class="muted">最多关联 4 个。每次检索按当前调用人的知识库权限执行。</p>
      <p v-if="!libraries.length" class="muted">暂无可关联知识库</p>
      <label v-for="row in libraries" :key="row.id" class="check-label">
        <input v-model="selectedKnowledge" type="checkbox" :value="row.id" /> {{ row.name }}
      </label>
    </div>
    <div class="form-wide tool-checks">
      <h2>MCP 工具</h2>
      <p class="muted">最多授权 12 个。调用仍遵守服务权限及审批。</p>
      <p v-if="!tools.length" class="muted">暂无可授权工具</p>
      <label v-for="row in tools" :key="row.key" class="check-label">
        <input v-model="selectedTools" type="checkbox" :value="row.key" /> {{ row.label }}
      </label>
    </div>
    <div class="form-wide form-actions">
      <el-button type="primary" native-type="submit" :loading="saving" :disabled="!!error && !libraries.length && !tools.length">保存授权</el-button>
    </div>
  </form>
</template>
