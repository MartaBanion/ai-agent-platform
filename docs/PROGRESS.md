# 项目进度

## 第一阶段 · 工程基线与核心服务部署

验收时间为 2026-11-27 12:25（UTC+08:00）。宿主机为 Ubuntu Server 24.04.5 LTS，4 核，Docker Engine 29.10.1，Docker Compose v5.8.0。Docker 已运行，复用了本机 Langflow 官方镜像，拉取了 PostgreSQL 17.12 官方镜像。

### 实测结果

| 验收项 | 结果 |
| --- | --- |
| Compose | `docker compose config --quiet` 通过，`docker compose up -d --wait` 等待到两个容器均为 `healthy` |
| PostgreSQL 17.12 | `platform_app → platform` 和 `langflow_app → langflow` 均成功。两个方向的交叉连接均被拒绝，两个账号都无超级用户、建库或建角色权限。Langflow 迁移版本为 `b7c9d1e3f508` |
| Langflow 1.13.4 | 本机首页和 `/health` 返回 200。匿名流程列表和自动登录返回 403，错误密码返回 401，管理员登录及认证后读取流程列表均返回 200 |
| 监听和密钥 | 宿主机访问 `192.168.61.132` 的 5432 和 7860 均被拒绝。仅发布 `127.0.0.1:7860`，PostgreSQL 位于内部网络。容器无 Docker Socket 挂载。`.env` 和 Langflow 持久卷中的密钥文件均为 `0600` |
| 持久化 | 保留命名卷并重建两个容器，管理员记录 ID、数据库迁移版本和 Langflow 密钥文件元数据保持一致；重建后两服务再次健康 |
| 容器稳定性 | 最终两容器 OOM 标志为 false、自动重启计数为 0，日志驱动为 `json-file`，单文件 10 MB、最多 3 份。首次启动时 Langflow 对 `/var/lib/langflow` 无写入权限，改用镜像内可写的 `/app/data` 后通过 |

### 资源快照

| 对象 | CPU | 内存 | 磁盘 |
| --- | ---: | ---: | ---: |
| 宿主机 | 3.60%（1 秒样本） | 2.1 GiB / 7.7 GiB，5.6 GiB 可用 | 13 GiB / 97 GiB，14%，80 GiB 可用 |
| PostgreSQL | 8.28% | 39.86 MiB / 1 GiB | 数据卷 78 MiB |
| Langflow | 0.29% | 1.296 GiB / 3 GiB | 数据卷 8.0 MiB |

容器 CPU 和内存来自 `docker stats --no-stream`，为重建后单次采样。CPU 配额分别为 1 核和 2 核。

### 版本安全核查

- Compose 固定 Langflow 1.13.4 官方镜像摘要。该版本发布说明列出 MCP 鉴权和隔离、自定义组件策略、匿名流程发布控制和依赖补丁。已核对的历史未授权执行及 MCP Stdio 执行公告所列修复版本早于 1.13.4。[1.13.4 发布说明](https://github.com/langflow-ai/langflow/releases/tag/v1.13.4) · [CVE-2025-3248](https://github.com/langflow-ai/langflow/security/advisories/GHSA-rvqx-wpfh-mfx7) · [公开流程执行公告](https://github.com/langflow-ai/langflow/security/advisories/GHSA-vwmf-pq79-vjvx) · [MCP Stdio 公告](https://github.com/langflow-ai/langflow/security/advisories/GHSA-7w94-79vh-5mr2)
- 按官方参数设置外部 PostgreSQL、持久配置目录、关闭自动登录、初始化管理员、设置签名密钥和单 worker。当前开发入口通过 SSH 隧道访问，命令及管理员初始化方式见 [README](../README.md)。[Docker 配置](https://docs.langflow.org/deployment-docker) · [环境变量](https://docs.langflow.org/environment-variables) · [认证配置](https://docs.langflow.org/api-keys-and-authentication)

### 验收范围

- 已在宿主机完成 HTTP 和认证测试。客户端 SSH 隧道需使用操作者的 SSH 凭据，尚无客户端端到端实测结果。
- 安全核查基于上游公告、发布说明和运行配置。完整镜像依赖扫描及负载测试留待后续。
- Nginx、Qdrant、Redis、Celery、监控及业务前后端留待后续阶段。

## 第二阶段 · 前后端框架与统一门户

2026-11-27 在原虚拟机部署。第一阶段的 PostgreSQL 与 Langflow 容器持续运行，复用既有数据卷。用户已确认第一阶段 Langflow 的客户端 SSH 隧道访问和登录成功。

### 已部署

- FastAPI 提供 `/api/v1`，通过 SQLAlchemy 连接独立 `platform` 业务库，Alembic 管理用户和可撤销会话表。Langflow 适配层通过内网 HTTP 健康接口执行连通性检查。
- 门户支持登录、退出、资料、修改密码、用户创建及分页查询、编辑角色、重置密码和启停账号。管理员、开发者与普通用户的权限由 API 校验。密码使用 Argon2，JWT 有效期为 30 分钟并存于 HttpOnly、SameSite=Strict Cookie。写请求校验防跨站请求标记，Nginx 按来源地址限制登录速率。
- Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router 生产产物由 Nginx 提供，门户与 API 使用同源访问。中文界面包含 13 个导航入口、可折叠菜单、响应式布局和主题切换。工作台及系统监控读取真实服务状态，账号总数和启用数仅向管理员显示；其余模块标明待建设。
- 门户监听 `127.0.0.1:8080`，Langflow 开发入口保留 `127.0.0.1:7860`。宿主机无 5432 或 8000 监听。四个容器均无 Docker Socket 挂载。Nginx 采用上游发布的 1.30.8 稳定修补版本。[Nginx 发布公告](https://nginx.org/2026.html)

### 验收

| 项目 | 实测结果 |
| --- | --- |
| 构建与部署 | `vue-tsc --noEmit`、`vite build`、`docker compose config --quiet`、`nginx -t`、`pip check` 均通过 |
| 迁移 | `alembic current` 为 `0001_users_sessions (head)`，`alembic check` 无缺失迁移 |
| 登录与权限 | `python3 tests/phase2_smoke.py` 通过。真实管理员登录返回 200，匿名 API 返回 401，普通用户和开发者访问管理员接口返回 403，跨站写请求防护返回 403，登录限流返回 429 |
| 用户管理与会话 | 用户创建、列表、编辑、重复用户名校验、角色变更、停用、改密和退出验证通过。角色和状态变更、改密及退出后旧会话失效。测试账号已清理 |
| 系统状态 | 工作台 API 返回业务库查询、账号统计与 Langflow HTTP 探测结果。原 Langflow 回环健康接口返回 200 |
| 浏览器 | 临时 Chromium 容器验证通过。覆盖受保护路由、登录、真实工作台、用户表和新增弹窗、主题切换、待建设页、移动导航及退出，无页面脚本异常 |
| 运行状态 | 四个服务健康，OOM 标志均为 false，自动重启计数均为 0 |

### 资源快照

采样时间为 2026-11-27 12:48（UTC+08:00）。宿主机负载均值为 0.09 / 0.19 / 0.24，内存已用 2.3 GiB / 7.7 GiB，5.4 GiB 可用。根文件系统已用 14 GiB / 97 GiB，15%，可用 79 GiB。

| 容器 | CPU | 内存 |
| --- | ---: | ---: |
| Nginx 门户 | 0.00% | 2.551 MiB / 64 MiB |
| FastAPI | 0.28% | 68.76 MiB / 384 MiB |
| PostgreSQL | 0.24% | 56.64 MiB / 1 GiB |
| Langflow | 0.95% | 1.321 GiB / 3 GiB |

本阶段在宿主机验证门户回环入口。客户端 8080 隧道仍需从操作者的设备验证。RAG、MCP、任务调度、审计查询及生产级监控留待后续，当前记录基础结构化请求及安全事件。
