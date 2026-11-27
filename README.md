# Enterprise AI Agent Platform

企业级 AI 智能体平台

## 项目定位

面向企业业务场景的 AI 智能体平台，集成智能体编排、
知识库检索、模型管理、工具调用、安全治理及运维监控。

## 技术选型

- Frontend: Vue3 + TypeScript + Element Plus
- Backend: FastAPI + SQLAlchemy + Alembic
- Agent Engine: Langflow
- Database: PostgreSQL
- Vector Database: Qdrant
- Cache: Redis
- Integration: MCP + REST API
- Deployment: Docker Compose / Kubernetes
- Monitoring: Prometheus + Grafana + Langfuse

## 架构原则

- Modular Monolith（模块化单体）
- Loose Coupling（低耦合）
- Security by Design（安全优先）
- Progressive Deployment（渐进式部署）
- Automated Testing（自动化测试）

## 开发环境

- OS: Ubuntu Server 24.04 LTS
- CPU: 4 Cores
- RAM: 8GB
- Disk: 100GB
- Virtualization: VMware

## 项目进度

V0.4 - 知识库、多语言语义检索与 MCP 工具中心

## 第四阶段验收入口

访问现有 8080 门户。在「知识库管理」新建本地 E5-small 知识库，上传文档，等待显示「可检索」后执行检索测试并打开结果中的原文引用。在「MCP 工具中心」选中「企业运维工具」，打开 `current_time` 的参数和调试窗口，填入 `{"zone":"UTC"}` 并提交审批，管理员可查看结果和耗时。在「智能体管理」使用「关联资源」选择知识库和授权工具。

新环境启动第四阶段前运行 `python3 scripts/provision_phase4.py`，生成内部服务密钥并安装经校验的本地 Embedding 文件。文档原文及片段保存在业务数据库，向量保存在 Qdrant 数据卷。可选云端 Embedding 配置见 `.env.example`。

## 第三阶段配置

门户管理员经 8080 SSH 隧道进入「模型管理」，新增服务商、模型标识和 API Key，测试连接后启用并设为默认模型。OpenAI、DeepSeek、Qwen 使用固定官方地址，自定义 OpenAI-compatible 服务使用公开 HTTPS 443 地址。模型密钥由后端加密保存，`PLATFORM_MODEL_KEY` 应随受限部署配置安全备份。

「企业 IT 智能运维助手」已创建为草稿并关联 Langflow 模型对话流程。配置启用的 OpenAI 或 DeepSeek 模型后，在「智能体管理」选择该模型并调试，按需发布。Qwen 和自定义服务可用于普通模型对话。现有 Langflow 编排入口仍通过 7860 SSH 隧道和独立 Langflow 登录访问。

新部署可在宿主机运行 `python3 scripts/provision_langflow.py` 配置非管理员引擎服务账号及模型加密密钥，随后重建后端并运行 `python3 scripts/seed_ai.py` 初始化内置流程和助手。当前实例已执行这两步。

## 统一门户

门户通过 Nginx 提供 Vue 生产构建产物和同源 `/api/v1` 接口。在客户端建立隧道后打开 `http://127.0.0.1:8080/`。

```sh
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8080:127.0.0.1:8080 ubuntu@192.168.61.132
```

当前门户管理员用户名是 `portal_admin`，初始密码位于虚拟机项目根目录的 `.env` 中，变量为 `PLATFORM_ADMIN_PASSWORD`。在私有 SSH 终端查看该项，登录后通过个人设置修改密码。初始化配置只在没有可用管理员时生效。门户账号独立于 Langflow 账号。

新环境按 `.env.example` 生成独立的 `PLATFORM_ADMIN_PASSWORD` 和 `PLATFORM_JWT_SECRET`，将 `.env` 权限设为 `0600`，然后运行 `docker compose up -d --build --wait`。后端启动时通过 Alembic 迁移业务库，再初始化管理员。当前回环入口由 SSH 提供传输加密，启用 HTTPS 时设置 `PLATFORM_COOKIE_SECURE=true`。

在刚初始化且仍使用初始管理员密码的部署上，执行 `python3 tests/phase2_smoke.py` 可验证生产前端产物、API、权限、会话、账号管理及登录限流。脚本需要本机 Docker 权限以清理此次测试创建的账号。

## 第一阶段开发入口

PostgreSQL 和 Langflow 由根目录的 `compose.yaml` 管理。新环境以 `.env.example` 为模板填写五个独立随机值，将 `.env` 权限设为 `0600`，然后执行 `docker compose config --quiet` 和 `docker compose up -d --wait`。首次启动在 PostgreSQL 数据卷中创建 `platform` 和 `langflow` 两套数据库及账号，并在 Langflow 中初始化管理员。

当前虚拟机的 Langflow 监听 `127.0.0.1:7860`。在客户端建立 SSH 隧道后打开浏览器的 `http://127.0.0.1:7860/`：

```sh
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:7860:127.0.0.1:7860 ubuntu@192.168.61.132
```

当前管理员用户名是 `platform_admin`，初始密码保存在虚拟机项目根目录 `.env` 的 `LANGFLOW_SUPERUSER_PASSWORD` 项。请在受限终端查看。

初始化 SQL 只在 PostgreSQL 数据卷首次启动时执行。持久卷中的账号变更应通过数据库或 Langflow 的管理接口操作，并同步更新连接配置。实际验收记录见 [docs/PROGRESS.md](docs/PROGRESS.md)。
