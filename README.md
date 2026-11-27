# Enterprise AI Agent Platform

企业级 AI 智能体平台。当前交付版本为 V0.4，覆盖统一门户、账号权限、Langflow 工作流、知识库语义检索和 MCP 工具中心。部署采用单机 Docker Compose，前端使用 Vue 3，业务 API 使用 FastAPI，业务与引擎使用独立 PostgreSQL 数据库，向量检索使用 Qdrant。

## 正式文档

| 阅读顺序 | 文档 | 内容 |
| --- | --- | --- |
| 01–02 | [项目说明与架构](docs/ARCHITECTURE.md) | 交付状态、组件取舍、部署拓扑、数据流、端口和存储 |
| 03–05 | [环境准备与部署](docs/DEPLOYMENT.md) | Ubuntu 准备、配置参数、服务启动、SSH 隧道和部署验证 |
| 06–08 | [平台使用与安全设计](docs/USER-GUIDE.md) | 使用步骤、实测截图、权限矩阵、凭据和出站安全 |
| 09–11 | [验收、运维、故障排查与开发](docs/OPERATIONS.md) | 自动化验收、状态巡检、更新、备份与隔离恢复、排障和交接 |
| 证据 | [阶段进度与验收记录](docs/PROGRESS.md) | 实际部署、实测结果、资源快照与阻塞 |

## 现有实例

Ubuntu 宿主机为 `192.168.61.132`，项目位于 `/home/ubuntu/ai-agent-platform`。门户和 Langflow 分别使用回环端口 `8080` 和 `7860`，经 [SSH 隧道](docs/DEPLOYMENT.md#052-从客户端访问) 访问。两套账号独立管理。

> **待验证：** 云端模型连接因 Fake-IP 触发 SSRF 防护，真实云推理及生成式 RAG 仍待验证。本地语义检索、Qdrant 持久化和内置 MCP 已实测。完整能力边界见 [项目状态表](docs/ARCHITECTURE.md#01-项目介绍)。

开发及自主验收约束见 [AGENTS.md](AGENTS.md)。
