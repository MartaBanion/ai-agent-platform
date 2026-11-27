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

V0.1 - 基础环境与引擎验证阶段

## 第一阶段开发入口

PostgreSQL 和 Langflow 由根目录的 `compose.yaml` 管理。新环境以 `.env.example` 为模板填写五个独立随机值，将 `.env` 权限设为 `0600`，然后执行 `docker compose config --quiet` 和 `docker compose up -d --wait`。首次启动在 PostgreSQL 数据卷中创建 `platform` 和 `langflow` 两套数据库及账号，并在 Langflow 中初始化管理员。

当前虚拟机的 Langflow 监听 `127.0.0.1:7860`。在客户端建立 SSH 隧道后打开浏览器的 `http://127.0.0.1:7860/`：

```sh
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:7860:127.0.0.1:7860 ubuntu@192.168.61.132
```

当前管理员用户名是 `platform_admin`，初始密码保存在虚拟机项目根目录 `.env` 的 `LANGFLOW_SUPERUSER_PASSWORD` 项。请在受限终端查看。

初始化 SQL 只在 PostgreSQL 数据卷首次启动时执行。持久卷中的账号变更应通过数据库或 Langflow 的管理接口操作，并同步更新连接配置。实际验收记录见 [docs/PROGRESS.md](docs/PROGRESS.md)。
