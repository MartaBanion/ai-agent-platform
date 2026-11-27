import { ApiError } from './api'

export interface ModelOption {
  id: string
  name: string
  provider: string
  model: string
  is_default: boolean
}

export interface Model extends ModelOption {
  enabled: boolean
  has_key: boolean
  base_url: string
  temperature: number
  max_tokens: number
  timeout: number
}

export interface Agent {
  id: string
  name: string
  description: string
  icon: string
  editable: boolean
  enabled: boolean
  published: boolean
  system_prompt?: string
  model_id?: string | null
  workflow_id?: string
}

export interface Workflow {
  id: string
  engine_id: string
  name: string
  description: string
  kind: 'echo' | 'prompt'
}

export interface Execution {
  id: string
  status: string
  duration_ms: number | null
  error: string | null
  created_at: string
  total_tokens: number | null
}

export async function stream(
  path: string, body: unknown, signal: AbortSignal, delta: (text: string) => void,
  started?: (id: string) => void,
) {
  const response = await fetch('/api/v1' + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Platform-Request': '1' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => null)
    if (response.status === 401) window.dispatchEvent(new Event('platform:unauthorized'))
    throw new ApiError(response.status, error?.error?.message ?? '无法开始生成')
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let pending = ''
  let done = false
  try {
    while (true) {
      const result = await reader.read()
      if (result.done) break
      pending += result.value
      let boundary: number
      while ((boundary = pending.indexOf('\n\n')) !== -1) {
        const frame = pending.slice(0, boundary).split('\n')
        pending = pending.slice(boundary + 2)
        const event = frame.find(line => line.startsWith('event: '))?.slice(7)
        const data = frame.find(line => line.startsWith('data: '))?.slice(6)
        if (!data) continue
        const payload = JSON.parse(data)
        if (event === 'start') started?.(payload.id)
        if (event === 'delta') delta(payload.text)
        if (event === 'error') throw new ApiError(502, payload.message)
        if (event === 'done') done = true
      }
    }
    if (!done) throw new ApiError(502, '连接提前结束，请重试')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export function isAbort(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
