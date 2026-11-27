export type Role = 'admin' | 'developer' | 'user'
export const roleLabels: Record<Role, string> = { admin: '管理员', developer: '开发者', user: '普通用户' }

export interface User {
  id: string
  username: string
  display_name: string
  role: Role
  is_active: boolean
  created_at: string
}

export interface Overview {
  services: { api: string; database: string; langflow: { status: string; latency_ms: number } }
  users: { total: number; active: number } | null
  checked_at: string
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export async function api<T>(path: string, method = 'GET', body?: unknown, timeout = 12000): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api/v1' + path, {
      method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Platform-Request': '1' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeout),
    })
  } catch {
    throw new ApiError(0, '无法连接平台，请检查连接后重试')
  }
  if (response.status === 204) return undefined as T
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') {
      window.dispatchEvent(new Event('platform:unauthorized'))
    }
    const fallback = response.status === 429 ? '登录尝试过多，请稍后重试' : '请求失败，请稍后重试'
    throw new ApiError(response.status, payload?.error?.message || fallback)
  }
  if (payload === null) throw new ApiError(response.status, '平台返回了无法识别的响应')
  return payload as T
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : '操作失败，请稍后重试'
}
