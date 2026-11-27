import { defineStore } from 'pinia'
import { api, ApiError, type User } from './api'

export const useAuth = defineStore('auth', {
  state: () => ({ user: null as User | null, ready: false, restoreError: '' }),
  actions: {
    async restore() {
      this.restoreError = ''
      try {
        this.user = await api<User>('/auth/me')
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) {
          this.restoreError = '暂时无法验证会话，请重试'
        }
        this.user = null
      } finally {
        this.ready = true
      }
    },
    async login(username: string, password: string) {
      this.user = await api<User>('/auth/login', 'POST', { username, password })
      this.restoreError = ''
    },
    async logout() {
      await api('/auth/logout', 'POST')
      this.user = null
    },
  },
})
