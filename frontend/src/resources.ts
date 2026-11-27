export interface Knowledge {
  id: string
  name: string
  description: string
  enabled: boolean
  shared: boolean
  editable: boolean
  profile: string
  dimension: number
  embedding: string
  chunk_size: number
  overlap: number
  top_k: number
  threshold: number
}

export interface Reference {
  reference: string
  document_id: string
  document: string
  knowledge: string
  page: number | null
  chunk: number
  text: string
  score: number
  download_url: string
}

export interface Tool {
  name: string
  description: string
  schema: Record<string, unknown>
}

export interface Server {
  id: string
  name: string
  kind: 'builtin' | 'external'
  url?: string
  has_key?: boolean
  enabled: boolean
  shared: boolean
  approval: boolean
  allowed: string[]
  tools: Tool[]
}

export interface ToolCall {
  id: string
  owner_id: string
  server_id: string | null
  agent_id: string | null
  name: string
  state: string
  error: string | null
  duration_ms: number | null
  arguments: Record<string, unknown> | null
  result: Record<string, unknown> | null
  created_at: string
}

export const callStates: Record<string, string> = { pending: '待审批', running: '执行中', success: '成功', failed: '失败', rejected: '已拒绝' }
