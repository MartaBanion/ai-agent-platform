# 项目开发规范

- 采用模块化单体。前端使用 Vue 3、TypeScript 和 Element Plus，后端使用 FastAPI、SQLAlchemy 和 Alembic。业务模块通过独立适配层调用 Langflow，业务数据归自主系统管理。
- PostgreSQL 存储业务与编排数据，Qdrant 提供向量检索，Redis 和 Celery 提供异步任务。集成接口使用 MCP 和 RESTful API，流式输出使用 SSE，平台身份与授权使用 JWT 和 RBAC。
- 使用 Docker Compose 管理服务，使用 Nginx 作为统一入口。优先使用云端模型 API。按阶段启用 Qdrant、Redis、Celery 和监控组件。
- 业务与 Langflow 使用独立数据库及最小权限账号。内部服务不映射宿主机端口。Langflow 开发入口必须登录，开发环境经 SSH 隧道访问。服务不得挂载 Docker Socket 或使用特权模式。
- 密钥放入受限的本地配置或密钥服务，禁止提交真实凭据、数据、备份和运行日志。日志脱敏，记录关键权限变更和管理行为。新增对外入口前核查认证、传输加密和依赖公告。
- 以 4 核、8 GB RAM、100 GB 标称磁盘为资源上限。为容器设置资源限制、健康检查、重启策略和日志轮转。变更持久化配置前备份并验证恢复路径。
- 尊重已有文件和用户变更。数据库变更走 Alembic，验证相关入口、权限和错误处理。在 `docs/PROGRESS.md` 登记实际执行、证据及阻塞。未经授权不得推送远程或清理持久化数据。
