import assert from 'node:assert/strict'
import bundled from '@sparticuz/chromium'
import { chromium } from 'playwright-core'

const origin = process.env.PORTAL_TEST_ORIGIN || 'http://127.0.0.1:8080'
const browser = await chromium.launch({ executablePath: await bundled.executablePath() })
const page = await browser.newPage({ viewport: { width: 1280, height: 850 }, acceptDownloads: true })
page.setDefaultTimeout(15000)
const jsErrors = []
page.on('pageerror', error => jsErrors.push(error.name))
const suffix = Date.now().toString(36)
const libraryName = '浏览器验收知识库 ' + suffix
const serverName = '浏览器验收 MCP ' + suffix
const agentName = '浏览器验收智能体 ' + suffix
let libraryId, serverId, agentId

async function api(path, method = 'GET', data) {
  const response = await page.request.fetch(origin + '/api/v1' + path, {
    method, data, headers: { 'Content-Type': 'application/json', 'X-Platform-Request': '1' },
  })
  assert.ok(response.ok(), path + ' HTTP ' + response.status())
  return response.status() === 204 ? null : response.json()
}

function created(path) {
  return page.waitForResponse(response => response.url().endsWith(path) &&
    response.request().method() === 'POST' && response.status() === 201)
}

function dialog(name) { return page.getByRole('dialog', { name }) }
function button(name, scope = page) { return scope.getByRole('button', { name, exact: true }) }
async function nav(name) { await page.getByRole('link', { name, exact: true }).click() }
async function closeModal() {
  await page.keyboard.press('Escape')
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
}
async function confirmDelete() {
  await button('确定', page.getByRole('dialog')).click()
}

try {
  await page.goto(origin + '/login')
  await page.locator('#login-user').fill(process.env.PLATFORM_ADMIN_USERNAME || 'portal_admin')
  await page.locator('#login-password').fill(process.env.PLATFORM_ADMIN_PASSWORD)
  await button('登录').click()
  await page.getByRole('heading', { name: '工作台', exact: true }).waitFor()
  await button('切换深色主题').click()
  assert.ok(await page.locator('html').evaluate(element => element.classList.contains('dark')))

  await nav('知识库管理')
  await button('新建知识库').click()
  const editor = dialog('新建知识库')
  await editor.getByLabel('名称', { exact: true }).fill(libraryName)
  const newLibrary = created('/api/v1/knowledge')
  await button('保存', editor).click()
  libraryId = (await (await newLibrary).json()).id
  await page.getByRole('heading', { name: libraryName, exact: true }).waitFor()
  await button('编辑').click()
  const editLibrary = dialog('编辑知识库')
  await editLibrary.getByLabel('描述', { exact: true }).fill('浏览器端验证真实索引')
  await button('保存', editLibrary).click()
  await page.getByText('浏览器端验证真实索引', { exact: true }).waitFor()
  await page.getByLabel('选择文档').setInputFiles({
    name: 'browser-knowledge.md', mimeType: 'text/markdown',
    buffer: Buffer.from('员工登录凭证丢失后，使用自助页面核验身份并重设账户密码。'),
  })
  await button('上传文档').click()
  const document = page.getByRole('row').filter({ hasText: 'browser-knowledge.md' })
  await document.getByText('可检索', { exact: true }).waitFor()
  await button('片段', document).click()
  await page.getByRole('dialog').getByText('员工登录凭证丢失后，使用自助页面核验身份并重设账户密码。', { exact: true }).waitFor()
  await closeModal()
  const download = page.waitForEvent('download')
  await document.getByRole('link', { name: '下载', exact: true }).click()
  assert.equal((await download).suggestedFilename(), 'browser-knowledge.md')
  await page.getByLabel('检索问题').fill('忘记了口令，怎么找回？')
  await button('执行检索').click()
  await page.locator('.reference-card').getByRole('link', { name: 'browser-knowledge.md' }).waitFor()
  const reprocessed = page.waitForResponse(response => response.url().endsWith('/reprocess') && response.status() === 202)
  await button('重处理', document).click()
  await reprocessed
  await document.getByText('可检索', { exact: true }).waitFor()

  await nav('MCP 工具中心')
  await button('注册服务').click()
  const register = dialog('注册 MCP 服务')
  await register.getByLabel('名称', { exact: true }).fill(serverName)
  const newServer = created('/api/v1/mcp/servers')
  await button('保存', register).click()
  serverId = (await (await newServer).json()).id
  await page.getByRole('heading', { name: serverName, exact: true }).waitFor()
  await button('连接测试与发现').click()
  await page.getByRole('row').filter({ hasText: 'current_time' }).waitFor()
  await button('编辑').click()
  const editServer = dialog('编辑 MCP 服务')
  await editServer.getByRole('checkbox', { name: 'current_time', exact: true }).check()
  await button('保存', editServer).click()
  const tool = page.getByRole('row').filter({ hasText: 'current_time' }).filter({ has: button('参数与调试') })
  await tool.getByText('已授权', { exact: true }).waitFor()

  const flows = await api('/workflows')
  agentId = (await api('/agents', 'POST', {
    name: agentName, workflow_id: flows.find(flow => flow.kind === 'echo').id,
  })).id
  await nav('智能体管理')
  const card = page.locator('.agent-card').filter({ hasText: agentName })
  await button('关联资源', card).click()
  const grants = dialog('关联知识库与工具')
  await grants.getByRole('checkbox', { name: libraryName, exact: true }).check()
  await grants.getByRole('checkbox', { name: serverName + ' · current_time', exact: true }).check()
  await button('保存授权', grants).click()
  await grants.waitFor({ state: 'hidden' })
  await button('调试与历史', card).click()
  await page.getByLabel('输入', { exact: true }).fill('口令丢了')
  await button('检索知识').click()
  await page.locator('.reference-card').getByRole('link', { name: 'browser-knowledge.md' }).waitFor()

  await nav('MCP 工具中心')
  await page.getByLabel('调用身份').selectOption(agentId)
  const approvedTool = page.getByRole('row').filter({ hasText: 'current_time' }).filter({ has: button('参数与调试') })
  await button('参数与调试', approvedTool).click()
  const debug = dialog('current_time · 参数与调试')
  await debug.getByLabel('工具参数（JSON）').fill('{"zone":"UTC"}')
  await button('提交审批', debug).click()
  const receipt = dialog('current_time · 调用记录')
  await receipt.getByText('待审批', { exact: true }).waitFor()
  await button('批准并执行', receipt).click()
  await receipt.locator('pre').getByText('"zone": "UTC"', { exact: false }).waitFor()
  await closeModal()

  await api('/agents/' + agentId, 'DELETE')
  agentId = undefined
  await page.getByLabel('调用身份').selectOption('')
  await page.getByRole('heading', { name: serverName, exact: true }).waitFor()
  await button('编辑').click()
  await editServer.getByRole('checkbox', { name: '启用', exact: true }).uncheck()
  await button('保存', editServer).click()
  await page.locator('.resource-menu').getByText('内置 · 停用').waitFor()
  await button('删除', page.locator('.resource-detail')).click()
  await confirmDelete()
  await page.getByRole('heading', { name: serverName, exact: true }).waitFor({ state: 'hidden' })
  serverId = undefined

  await page.setViewportSize({ width: 390, height: 844 })
  await button('切换导航').click()
  await nav('知识库管理')
  await page.locator('.resource-menu').getByText(libraryName, { exact: true }).click()
  await button('删除', document).click()
  await confirmDelete()
  await document.waitFor({ state: 'hidden' })
  await button('删除', page.locator('.resource-title')).click()
  await confirmDelete()
  await page.locator('.resource-menu').getByText(libraryName, { exact: true }).waitFor({ state: 'hidden' })
  libraryId = undefined
  assert.deepEqual(jsErrors, [])
  console.log('PASS Chromium 8080: knowledge CRUD, document upload/preview/download/reprocess/delete, real semantic citation, MCP registry/discovery/approval/result, agent links, dark and mobile navigation')
} finally {
  if (agentId) await api('/agents/' + agentId, 'DELETE').catch(error => console.error(error.message))
  if (serverId) await api('/mcp/servers/' + serverId, 'DELETE').catch(error => console.error(error.message))
  if (libraryId) await api('/knowledge/' + libraryId, 'DELETE').catch(error => console.error(error.message))
  await api('/auth/logout', 'POST').catch(() => {})
  await browser.close()
}
