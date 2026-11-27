# 环境准备与部署

[文档导航](../README.md) · [项目架构](ARCHITECTURE.md) · [平台使用](USER-GUIDE.md) · [运维与故障排查](OPERATIONS.md)

## 03 环境准备

**目标与完成标准**　确认宿主机资源、Docker 权限、下载条件和可用入口，明确当前实例与新部署的参数差异。

表 03-1　运行环境与可替换参数

| 项目 | 当前实测环境 | 新环境检查与替换 |
| --- | --- | --- |
| 宿主机 | Ubuntu Server 24.04 LTS，4 vCPU，约 8 GB RAM，标称 100 GB 磁盘 | 核对系统和架构，测试前留出构建缓存、模型和业务数据空间 |
| 项目路径 | `/home/ubuntu/ai-agent-platform` | 命令默认在实际 checkout 根目录运行。如果目录名不同，保持 Compose 项目名为 `ai-agent-platform` |
| 软件 | Docker Engine 29.10.1，Docker Compose v5.8.0 | 使用 Docker 官方 Engine 和 Compose 插件。Node 与应用 Python 在镜像中安装 |
| SSH | `ubuntu@192.168.61.132`，通常端口 22 | 替换为部署方实际账号、地址和 SSH 端口，确认允许本地端口转发 |
| 门户和引擎 | 宿主机 `127.0.0.1:8080`、`127.0.0.1:7860` | 只修改宿主机映射端口和隧道参数，保持回环绑定 |
| 下载 | Docker Hub、所用 Python 与 npm 软件仓库和 Hugging Face 模型仓库 | 构建前确认可通过获准网络下载。模型文件下载与运行时云模型访问是不同的路径 |

在 Ubuntu 宿主机检查已有环境：

```bash
cd /home/ubuntu/ai-agent-platform
cat /etc/os-release
uname -m
nproc
free -h
df -h .
git status --short --branch
docker version
docker compose version
systemctl is-active docker
ss -lnt '( sport = :8080 or sport = :7860 )'
```

全新部署预期端口空闲。已有实例预期两端口只监听回环地址。Docker 输出应包含服务端信息；仅显示客户端或报 socket 权限错误时，先按 [10.1](OPERATIONS.md#101-docker-或-ssh-入口不可用) 判断原因。

> **安全提示：** Docker 管理访问通常具有接近宿主机 root 的能力。仅授予受信运维账号，业务容器禁止挂载 Docker Socket。Docker 命令权限错误时不要给 socket 设置全员可写权限。

## 04 基础环境搭建

**目标与完成标准**　从干净 Ubuntu 和现有源码准备可启动的 Compose 环境，秘密只写入受限本地文件。

### 04.1 安装或复用 Docker

当前实例在项目启动前已有 Docker。下面是核对官方方法后的**新机推荐步骤**。已有 Docker 正常工作的主机跳到 04.2。

> **警告：** 若主机已有发行版 Docker、containerd 或生产容器，先评估并备份，安排迁移窗口。以下安装命令用于干净 Ubuntu，不适用于直接替换运行中引擎。

在 Ubuntu 宿主机执行。仓库证书用于验证 Docker 软件包签名，`docker-compose-plugin` 提供 `docker compose` 子命令。

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

. /etc/os-release
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
sudo docker run --rm hello-world
```

后续示例用已获 Docker 权限的受信账号运行。受管环境用组织提供的权限流程。Docker 安装来源和已有包的冲突信息见 [Docker 官方 Ubuntu 安装说明](https://docs.docker.com/engine/install/ubuntu/)。

新 Ubuntu 主机需要通过 SSH 管理且尚无 SSH 服务时，在有独立控制台和授权的前提下安装 OpenSSH。已有服务直接检查状态。在新终端验证现有管理账号可连接后，再依赖 SSH 部署。

```bash
sudo apt-get install -y openssh-server
sudo systemctl enable --now ssh
systemctl is-active ssh
```

访问限制应遵循环境既有策略。若 Docker 权限由本地 `docker` 组提供，仅在批准受信运维人选后执行 `sudo usermod -aG docker "$USER"`，重新登录后检查 `id -nG` 和 `docker version`。

### 04.2 准备源码与配置

在 Ubuntu 宿主机获得授权的 Git checkout，或将随交付提供的源码放到目标目录。仓库 URL 和源码获取方式由交付方提供。当前项目的命令假设：

```bash
cd /home/ubuntu/ai-agent-platform
test -f compose.yaml && test -f .env.example
git log -1 --oneline
git check-ignore .env data/embedding/model_quantized.onnx
```

以下命令**只用于尚未存在 `.env` 的新实例**。它从样板保留默认值，为不同用途生成独立密钥，且只输出文件权限。

```bash
umask 077
python3 - <<'PY'
import base64
import os
import secrets
from pathlib import Path

fields = {
    "POSTGRES_PASSWORD", "PLATFORM_DB_PASSWORD", "LANGFLOW_DB_PASSWORD",
    "LANGFLOW_SUPERUSER_PASSWORD", "PLATFORM_ADMIN_PASSWORD", "PLATFORM_JWT_SECRET",
    "PLATFORM_QDRANT_KEY", "PLATFORM_MCP_KEY",
}
values = {key: secrets.token_hex(32) for key in fields}
values["LANGFLOW_SECRET_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
lines = Path(".env.example").read_text().splitlines()
with Path(".env").open("x") as handle:
    handle.write("\n".join(
        key + "=" + values[key] if (key := line.split("=", 1)[0]) in values else line
        for line in lines
    ) + "\n")
PY
stat -c '%a %n' .env
docker compose config --quiet
```

> **重要：** 即使只启动 PostgreSQL 和 Langflow，Compose 也会解析其他服务的必填变量。请在首次执行 Compose 前填写 Qdrant 和 MCP 密钥。密码与模型密钥不可提交、截图或粘贴到排障记录。语法检查使用 `--quiet`，普通 `docker compose config` 会输出插值结果。

> **环境差异：** 当前运行实例的 Langflow 签名密钥来自第一阶段，保留原格式。上述 Fernet 格式用于新环境推荐配置；不要直接用这段命令替换已有密钥。当前集成使用非管理员 Bearer 会话，签名密钥的历史问题见 [10.3](OPERATIONS.md#103-langflow-健康但执行失败)。

表 04-1　根目录 `.env` 配置分组

| 配置项 | 用途与当前用法 | 修改后处理及验证 |
| --- | --- | --- |
| `POSTGRES_PASSWORD`、`PLATFORM_DB_PASSWORD`、`LANGFLOW_DB_PASSWORD` | PostgreSQL 管理员及两套业务角色。数据库密码采用十六进制，适配现有 DSN | 持久库轮换同时更新数据库角色和消费者配置。单独修改环境文件不会改已有角色 |
| `LANGFLOW_SUPERUSER`、`LANGFLOW_SUPERUSER_PASSWORD`、`LANGFLOW_SECRET_KEY` | 独立引擎管理员、初始口令与引擎签名 | 已有账号改密通过引擎管理界面执行。签名密钥轮换先备份并验证影响 |
| `PLATFORM_ADMIN_USERNAME`、`PLATFORM_ADMIN_PASSWORD`、`PLATFORM_JWT_SECRET` | 门户初始管理员及 JWT 签名。默认管理员名 `portal_admin` | 初始化只在缺少可用管理员时执行。现有账号在门户改密。JWT 密钥变更会使既有令牌失效 |
| `LANGFLOW_PORT`、`PORTAL_PORT` | 宿主机两个回环端口，默认为 7860 和 8080 | 调整后重建映射服务，修改 SSH 隧道。编辑器跳转地址由后端读取 `LANGFLOW_PORT`，更改该值时也重建后端 |
| `PLATFORM_COOKIE_SECURE` | 当前回环 HTTP 通过 SSH 访问，模板值为 `false` | 新增正式 HTTPS 入口时评估设为 `true`，随后重建后端并验证登录 |
| `PLATFORM_MODEL_KEY`、`PLATFORM_LANGFLOW_SERVICE_PASSWORD` | 初始化脚本生成的 Fernet 密钥与非管理员引擎凭据 | 后端重建后加载。加密密钥必须备份，替换会影响已加密凭据的读取 |
| `PLATFORM_QDRANT_KEY`、`PLATFORM_MCP_KEY` | 内部 Qdrant 和内置工具服务认证 | 在协调窗口重建提供端和后端，分别验证检索及 MCP 调用 |
| `EMBEDDING_CLOUD_URL`、`EMBEDDING_CLOUD_MODEL`、`EMBEDDING_CLOUD_DIMENSION`、`EMBEDDING_CLOUD_KEY` | 可选云端 Embedding，当前本地流程保持未配置 | 需要合规公网 HTTPS、有效凭据和维度配置。重建后端后为新知识库选择云端，已有索引保留原配置 |

项目目录采用其他名称时，在首次启动前用受限编辑器在 `.env` 添加 `COMPOSE_PROJECT_NAME=ai-agent-platform`。内置 MCP 使用后端构建产生的 `ai-agent-platform-backend` 镜像名；保持项目名可使后续脚本和 Compose 复用同一组网络与卷。在已有宿主机上不要用同一项目名启动另一套实例。

## 05 核心服务部署

**目标与完成标准**　启动六个健康服务，业务库迁移到当前版本，通过回环验证，再通过 SSH 打开两个独立入口。

### 05.1 按依赖顺序启动

在 Ubuntu 项目根目录执行。以下是基于当前配置编排的**推荐重建顺序**。历史阶段的实际启动和修复见 [PROGRESS.md](PROGRESS.md)。

```bash
python3 scripts/provision_phase4.py
docker compose up -d --wait --wait-timeout 240 postgres langflow
curl --fail --silent --show-error http://127.0.0.1:7860/health
python3 scripts/provision_langflow.py
```

- `provision_phase4.py` 生成缺失的内部凭据，下载固定版本 ONNX 和 tokenizer 到 `data/embedding`，校对 SHA-256。它复用已通过验证的文件。
- PostgreSQL 空卷首次启动时执行 [初始化 SQL](../infrastructure/postgres/10-databases.sql)，创建 `platform` 和 `langflow` 及各自普通角色，取消公共数据库访问权限。Langflow 使用独立登录和可写的 `/app/data`。
- `provision_langflow.py` 需要本机 Langflow 已可登录。它建立或认证非管理员服务账号并生成门户加密密钥。成功时输出可认证及发现内置模板的结果，密钥仍在 `.env`。

```bash
docker compose config --quiet
docker compose build backend portal
docker compose up -d --wait --wait-timeout 240
docker compose ps
docker compose exec -T backend alembic current
docker compose exec -T backend alembic check
docker compose exec -T portal nginx -t
curl --fail --silent --show-error http://127.0.0.1:8080/portal-health
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/health
```

后端入口先执行 `alembic upgrade head` 再初始化管理员。门户镜像通过 `npm ci` 使用锁文件，通过 `vue-tsc` 与 Vite 构建，再交给 Nginx。Qdrant 采用固定摘要，首次启动创建命名卷。内置工具使用后端构建镜像独立运行。预期六个服务显示 `healthy`，业务库版本为 `0003_knowledge_tools (head)`，Nginx 语法检查成功。

> **注意：** 示例使用当前回环端口。新环境使用其他端口时替换 `curl` 目标及客户端隧道参数。镜像或模型下载失败时检查对应仓库和获准出站路径，不要跳过模型校验。

新实例需要初始化文本直通工作流和 IT 助手时，在宿主机执行：

```bash
python3 scripts/seed_ai.py
```

脚本通过同源门户 API 使用 `.env` 中的初始管理员凭据。适用于首次初始化且初始口令尚未修改的部署。已改密的实例使用门户创建对应模板和智能体，不要为了运行脚本重置现有账号。

### 05.2 从客户端访问

Windows PowerShell 或带 OpenSSH 客户端的 Linux/macOS 终端执行。先使用 `ssh -V` 检查本机客户端。保持该终端窗口打开：

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8080:127.0.0.1:8080 -L 127.0.0.1:7860:127.0.0.1:7860 ubuntu@192.168.61.132
```

`-N` 仅转发。每个 `-L` 前半段是客户端绑定和端口，后半段是 SSH 宿主机看到的目标。若客户端端口已占用，可把第一个本地 `8080` 改成 `18080`，随后浏览 `http://127.0.0.1:18080/`。使用非默认 SSH 端口时增加 `-p` 和实际端口。收到主机指纹提示时，应由受信来源核对后保存。

> **验收标准：** 浏览器打开 `http://127.0.0.1:8080/` 显示门户登录，打开 `http://127.0.0.1:7860/` 显示独立 Langflow 登录。数据库、Qdrant、FastAPI 和内置 MCP 没有宿主机监听。登录和功能验收由项目执行方自动完成。

### 05.3 配置文件生效规则

| 路径 | 用途 | 生效与验证 |
| --- | --- | --- |
| [compose.yaml](../compose.yaml) | 镜像、网络、绑定、资源、环境变量和卷 | `docker compose config --quiet`，然后用 `up` 重建受影响服务，核对健康和端口 |
| [frontend/nginx.conf](../frontend/nginx.conf) | 安全头、上传上限、登录限流及 SSE 转发 | 配置复制进镜像，修改后构建并重建 `portal`，再运行 `nginx -t` |
| [backend/Dockerfile](../backend/Dockerfile)、[backend/requirements.txt](../backend/requirements.txt) | 应用运行环境，内置工具共用镜像 | 两服务依赖同一镜像，升级时按需重建 `backend` 和 `ops`，验证迁移和 MCP 调用 |
| [初始化 SQL](../infrastructure/postgres/10-databases.sql) | 空数据库卷的角色与库初始化 | 对已有卷修改此文件不会重新执行。已有库使用受审迁移或数据库管理命令 |
