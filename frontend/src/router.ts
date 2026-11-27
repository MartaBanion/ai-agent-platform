import type { Component } from 'vue'
import { createRouter, createWebHistory, type RouteRecordSingleView } from 'vue-router'
import { ChatDotRound, Connection, Cpu, DataAnalysis, Document, Files, Grid, House, Key, Management, Monitor, Operation, Setting } from '@element-plus/icons-vue'
import { useAuth } from './auth'
import Workspace from './views/Workspace.vue'
import Login from './views/Login.vue'
import Dashboard from './views/Dashboard.vue'
import Users from './views/Users.vue'
import Settings from './views/Settings.vue'
import Pending from './views/Pending.vue'

interface NavItem {
  path: string
  title: string
  icon: Component
  component?: RouteRecordSingleView['component']
  admin?: boolean
  builder?: boolean
}

export const sections: { title: string; items: NavItem[] }[] = [
  { title: '工作空间', items: [
    { path: '/workbench', title: '工作台', icon: House, component: Dashboard },
    { path: '/chat', title: 'AI 对话', icon: ChatDotRound, component: () => import('./views/Chat.vue') },
    { path: '/agents', title: '智能体管理', icon: Cpu, component: () => import('./views/Agents.vue') },
    { path: '/workflows', title: '工作流管理', icon: Connection, component: () => import('./views/Workflows.vue'), builder: true },
    { path: '/knowledge', title: '知识库管理', icon: Files },
    { path: '/models', title: '模型管理', icon: DataAnalysis, component: () => import('./views/ModelCenter.vue'), admin: true },
    { path: '/mcp', title: 'MCP 工具中心', icon: Operation },
    { path: '/apps', title: '应用中心', icon: Grid },
    { path: '/tasks', title: '任务中心', icon: Management },
  ] },
  { title: '平台管理', items: [
    { path: '/users', title: '用户与权限', icon: Key, component: Users, admin: true },
    { path: '/audit', title: '日志与审计', icon: Document, admin: true },
    { path: '/status', title: '系统监控', icon: Monitor, component: Dashboard },
    { path: '/settings', title: '系统设置', icon: Setting, component: Settings },
  ] },
]

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: Login },
    { path: '/', component: Workspace, children: [
      { path: '', redirect: '/workbench' },
      ...sections.flatMap(section => section.items.map(item => ({
        path: item.path.slice(1),
        component: item.component ?? Pending,
        meta: { title: item.title, admin: item.admin ?? false, builder: item.builder ?? false },
      }))),
      { path: ':pathMatch(.*)*', component: Pending, meta: { title: '页面未找到', missing: true } },
    ] },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (!auth.ready) await auth.restore()
  if (!auth.user && to.path !== '/login') return '/login'
  if (auth.user && to.path === '/login') return '/workbench'
  if (to.meta.admin && auth.user?.role !== 'admin') return '/workbench'
  if (to.meta.builder && auth.user?.role === 'user') return '/workbench'
})
