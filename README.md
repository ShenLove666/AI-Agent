# RAGent Python

一个面向电商商家服务与私有知识库的 RAG 应用。后端使用 Python 与 FastAPI，前端使用 React 18；整体按模块化单体组织。当前版本优先使用大模型 API，未配置本地 Embedding 时也能以关键词检索运行，适合先把商家 AI 产品流程跑通，再逐步接入向量库和本地模型。

## 目前具备的能力

- JWT 注册与登录，用户数据、会话和知识库相互隔离
- 多知识库管理，支持上传 TXT、Markdown、PDF 和 DOCX；格式与 50MB 大小限制由服务端强制校验
- 文档解析、结构化切块与向量索引；Pipeline 模块保留为后续演进基础，当前上传链路使用直接分块
- 关键词与向量检索通道并发执行，单个通道异常不会拖垮整次请求
- 基于数据库 Chunk ID 的 Weighted RRF 真正融合、可选 CrossEncoder 重排和元数据补全
- 查询改写、引用生成、同步回答与 SSE 流式回答
- 对话可选择全部或指定知识库作为检索范围，关键词与向量通道使用同一 Scope
- 深度思考模式：按供应商切换推理模型/思考开关，并流式展示、持久化思考过程
- SSE 请求幂等、首 Token/空闲/总生成超时和即时取消传播
- 失败重试保持 Prompt 历史一致，空模型回答触发故障转移，失败消息返回真实数据库 ID
- 流式聊天使用 JSON POST，问题不会进入 URL；requestId 指纹防止不同请求误复用缓存
- 大模型多供应商优先级、故障转移和三态熔断器
- RAG Trace：记录改写、检索、Prompt 和生成节点的耗时与状态
- 商家运营洞察：统计 AI 工具渗透率、反馈覆盖率、回答好评率、知识命中率和高频经营意图
- Agent 质量运营：将负反馈、知识未命中、慢响应和失败运行转化为可导出的诊断报告与优化动作
- SQLite 默认零配置运行；可选 Milvus 和本地 SentenceTransformer
- 新版管理界面覆盖对话、知识库、运行追踪和系统状态

## 技术结构

```text
Browser
  └─ React 18 / Vite
       └─ /api/v1
            └─ FastAPI
                 ├─ users / conversations / knowledge
                 ├─ ingestion pipeline
                 ├─ retrieval engine
                 │    ├─ keyword
                 │    └─ vector (optional)
                 ├─ query rewrite / RAG chat / trace
                 └─ model router
                      ├─ primary API
                      └─ backup API (optional)
```

核心目录：

```text
app/
├─ api/                # HTTP 接口与依赖
├─ framework/          # 配置、数据库、错误响应、Trace ID
├─ infra_ai/           # 模型协议、供应商适配、路由与熔断
└─ modules/
   ├─ users/
   ├─ conversations/
   ├─ knowledge/
   ├─ ingestion/
   ├─ retrieval/
   ├─ vector/
   └─ rag/
web/src/               # React 管理界面
tests/                 # 架构、业务、检索、RAG 与前端入口测试
legacy/                # 改造前代码，只作迁移参考
```

## 使用 uv 本地启动

环境要求：Python 3.11+、[uv](https://docs.astral.sh/uv/)、Node.js 18+。

### 1. 创建虚拟环境并安装依赖

PowerShell：

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
```

`requirements-dev.txt` 是 API 优先的精简环境，不会下载 PyTorch、BGE-M3 或 PaddleOCR 等大体积模型依赖。

### 2. 配置大模型 API

当前内置 DeepSeek 作为主供应商；也可以配置任意 OpenAI 兼容接口作为备用供应商。

```powershell
$env:DEEPSEEK_API_KEY = "替换为自己的密钥"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
$env:DEEPSEEK_MODEL = "deepseek-chat"
$env:DEEPSEEK_REASONING_MODEL = "deepseek-reasoner"

# 可选备用接口
$env:BACKUP_LLM_API_KEY = "替换为备用密钥"
$env:BACKUP_LLM_BASE_URL = "https://example.com/v1"
$env:BACKUP_LLM_MODEL = "model-id"
$env:BACKUP_LLM_REASONING_MODEL = "reasoning-model-id"
```

密钥只放在环境变量或服务器的私密环境文件中，不要提交到 Git。

### 3. 构建界面并启动

```powershell
Set-Location web
npm install
npm run build
Set-Location ..

uv run python server.py
```

浏览器访问 `http://127.0.0.1:8081`。FastAPI 会直接托管 `web/dist`，生产环境不需要再暴露 Vite 的 3000 端口。

开发界面时可使用热更新：

```powershell
# 终端 1
uv run python server.py

# 终端 2
Set-Location web
npm run dev
```

此时访问 `http://127.0.0.1:3000`，Vite 会把 `/api` 转发到 8081。

## 检索模式

### 轻量模式（默认）

不设置 `EMBED_MODEL_PATH`。系统使用 jieba 关键词检索和 SQLite，适合开发、接口联调和小数据演示，没有模型下载成本。

### 本地小模型 + 内存向量库

安装 `sentence-transformers` 后设置本地模型目录：

```powershell
$env:EMBED_MODEL_PATH = "D:\models\bge-small-zh-v1.5"
$env:EMBED_DIMENSION = "512"
$env:VECTOR_BACKEND = "memory"
```

可使用体积更小的中文 Embedding 模型，不强制下载 BGE-M3。`EMBED_DIMENSION` 必须与所选模型实际输出维度一致。内存后端适合开发，服务重启后应重新索引。

### Milvus 持久化向量

```powershell
$env:VECTOR_BACKEND = "milvus"
$env:MILVUS_URI = "http://127.0.0.1:19530"
$env:MILVUS_COLLECTION = "ragent_chunks_v2"
```

需要精排时，再单独设置 `RERANK_MODEL_PATH`；不设置就不会加载 Reranker。

## 常用配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DB_URL` | `sqlite:///./data/ragent.db` | SQLAlchemy 数据库地址 |
| `API_PREFIX` | `/api/v1` | API 统一前缀 |
| `CORS_ORIGINS` | `http://localhost:3000` | 逗号分隔的跨域来源 |
| `RETRIEVAL_TIMEOUT_SECONDS` | `8` | 检索通道超时 |
| `RETRIEVAL_CANDIDATE_LIMIT` | `20` | 融合前候选数 |
| `RETRIEVAL_CONTEXT_LIMIT` | `6` | 进入 Prompt 的上下文数 |
| `CHAT_TIMEOUT_SECONDS` | `120` | 模型调用超时 |
| `CHAT_FIRST_TOKEN_TIMEOUT_SECONDS` | `20` | 流式生成首 Token 超时 |
| `CHAT_IDLE_TIMEOUT_SECONDS` | `30` | 流式生成 Token 间最大空闲时间 |
| `MAX_UPLOAD_FILE_SIZE` | `52428800` | 服务端允许的单文件最大字节数 |
| `DEEPSEEK_REASONING_MODEL` | `deepseek-reasoner` | 开启深度思考时使用的 DeepSeek 模型 |
| `MIMO_REASONING_MODEL` | 与普通模型相同 | 小米 MiMo 深度思考模型；同时发送 thinking 开关 |
| `BACKUP_LLM_REASONING_MODEL` | 未设置 | 备用接口的推理模型 ID |
| `CIRCUIT_FAILURE_THRESHOLD` | `3` | 供应商熔断阈值 |
| `CIRCUIT_RECOVERY_SECONDS` | `30` | 熔断恢复等待时间 |

## API 概览

所有业务接口位于 `/api/v1`：

| 模块 | 主要接口 |
|---|---|
| 系统 | `GET /health`、`GET /architecture` |
| 鉴权 | `POST /auth/register`、`POST /auth/login` |
| 会话 | `GET/POST /conversations`、`PATCH /conversations/{id}`、`GET /conversations/{id}/messages` |
| 知识库 | `GET/POST /knowledge-bases`、上传/查询/删除文档 |
| 对话 | `POST /chat`、`POST /chat/stream` |
| 管理 | `GET /management/traces`、`/models`、`/settings` |
| 商家运营 | `GET /admin/dashboard/operations`（渗透、质量、意图与问题诊断） |

启动后可在 `/docs` 查看 OpenAPI 文档。

客户端可为每轮问答传入 `request_id`（流式兼容接口使用 `requestId`）。服务端会持久化请求状态；重复提交已完成的请求会直接回放原回答，处理中的重复请求会被拒绝，失败请求则允许安全重试。

流式兼容接口为 `POST /api/v1/rag/v3/chat`，请求体使用 JSON。幂等指纹覆盖会话、问题、RAG/深度思考开关和知识库范围；相同 `requestId` 携带不同参数会返回 `409 IDEMPOTENCY_CONFLICT`。手动停止的请求记录为 `cancelled`，不会把部分回答作为成功缓存回放。

深度思考模式会把模型的 reasoning 增量以独立 SSE 事件返回，并随助手消息持久化；刷新页面后，思考内容、思考耗时、引用、投票、消息状态和推荐问题均可恢复。

聊天输入区的“全部知识库”菜单可选择一个或多个知识库。空选择表示检索当前用户的全部知识库；指定后，后端会同时约束关键词和向量检索通道。

### 管理员账号

首次部署可创建管理员：

```powershell
.\.venv\Scripts\python.exe -m app.cli create-admin --username admin
```

如果已经注册了同名普通账号，可由拥有服务器文件权限的运维人员显式提升；提升后必须退出并重新登录：

```powershell
.\.venv\Scripts\python.exe -m app.cli promote-admin --username admin
```

## 测试

```powershell
uv run python -m pytest -q
```

测试使用临时 SQLite 数据库，不依赖已经启动的 8081 服务。目前覆盖鉴权、会话、文档入库、检索融合、向量检索、RAG 对话、运行追踪和 SPA 路由。

## 服务器部署提示

服务监听 `0.0.0.0:8081`。对外部署时建议只让 Nginx/Caddy 暴露 80 或 443，并反向代理到 `127.0.0.1:8081`；前后端使用同一个入口，可避免登录请求跳到错误端口。若浏览器仍访问到旧的 8080 地址，应清理旧前端缓存并确认反向代理配置没有保留旧 `/login` 路由。

更详细的演进说明见：

- `docs/python-ragent-architecture.md`
- `docs/python-migration-status.md`
- `docs/python-phase3-vector-and-trace.md`
- `docs/production-rag-reliability.md`
- `docs/chat-product-completeness.md`
- `docs/v2.1-state-and-retrieval-scope.md`
- `docs/v2.2-pre-turn-consistency.md`
