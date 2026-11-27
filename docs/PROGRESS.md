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
