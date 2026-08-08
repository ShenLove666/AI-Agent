# 邻里鲜选 AI 运营台

一个面向即时零售商家的 AI 产品运营项目。后端使用 Python 与 FastAPI，前端使用 React 18；用真实购物篮关系串联运营洞察、搭配购方案、AI 客服、Agent 评测、优化任务和周报输出。

## 最快查看即时零售效果

项目数据库已导入用户授权的购物篮数据时，只需：

```powershell
.\.venv\Scripts\python.exe server.py
```

访问 `http://127.0.0.1:8081/login`，使用 `merchant-demo / AdminDemo@2026` 登录后进入“即时零售运营”。日常启动不需要重复执行 `npm install` 或 `npm run build`。

首次完整初始化（会导入项目内已校验快照、12 篇知识和 360 条来源关联案例）：

```powershell
uv pip install --python .\.venv\Scripts\python.exe -r requirements-api.txt
.\.venv\Scripts\python.exe scripts\setup_local_ai.py
$env:DEMO_SEED_PASSWORD = "AdminDemo@2026"
.\.venv\Scripts\python.exe -m app.cli seed-demo --reset
```

数据口径：授权数据贡献 9,835 个匿名购物篮和 43,367 条商品出现记录，不含价格、时间、顾客、门店或履约；UCI Online Retail II 的 CC BY 4.0 固定快照贡献 5,000 条带时间、数量、英镑单价、国家和取消标记的公开交易。两份数据分别记录 lineage，不混合声称销售增长。授权原始目录只读，仓库保存确定性 gzip 快照与 SHA256 清单。

## 目前具备的能力

- JWT 注册与登录，用户数据、会话和知识库相互隔离
- 多知识库管理，支持上传 TXT、Markdown、PDF 和 DOCX；格式与 50MB 大小限制由服务端强制校验
- 文档解析、结构化切块与向量索引；Pipeline 模块保留为后续演进基础，当前上传链路使用直接分块
- 关键词与向量检索通道并发执行，单个通道异常不会拖垮整次请求
- 基于数据库 Chunk ID 的 Weighted RRF 真正融合、可选 CrossEncoder 重排和元数据补全
- LangGraph ReAct 查询规划、工具自主路由、证据审查、受限重试、引用生成、同步回答与 SSE 流式回答
- 对话可选择全部或指定知识库作为检索范围，关键词与向量通道使用同一 Scope
- 深度思考模式：按供应商切换推理模型/思考开关，并流式展示、持久化思考过程
- SSE 请求幂等、首 Token/空闲/总生成超时和即时取消传播
- 失败重试保持 Prompt 历史一致，空模型回答触发故障转移，失败消息返回真实数据库 ID
- 流式聊天使用 JSON POST，问题不会进入 URL；requestId 指纹防止不同请求误复用缓存
- 大模型多供应商优先级、故障转移和三态熔断器
- RAG Trace：记录改写、检索、Prompt 和生成节点的耗时与状态
- 商家运营洞察：统计 AI 工具渗透率、反馈覆盖率、回答好评率、知识命中率和高频经营意图
- 即时零售购物篮分析：计算支持度、置信度、提升度并下钻真实订单证据
- 从关联规则创建搭配购方案，展示 Agent 评测运行、优化任务状态与证据化周报
- 规则化质量运营：将负反馈、知识未命中、慢响应和失败运行转化为可导出的诊断报告与优化动作
- SQLite 业务库 + 项目内 Milvus Lite 3.2 持久化向量库；本地 BGE-small-zh-v1.5 已下载并实测 512 维检索
- 新版管理界面覆盖对话、知识库、运行追踪和系统状态

## 技术结构

```text
Browser
  └─ React 18 / Vite
       └─ /api/v1
            └─ FastAPI
                 ├─ users / conversations / knowledge
                 ├─ ingestion pipeline
                 ├─ LangGraph ReAct coordinator
                 │    ├─ knowledge_search (keyword + Milvus)
                 │    ├─ commerce_data (verified SQL snapshots)
                 │    └─ support_cases (provenance-aware SQL)
                 ├─ evidence review / bounded retry / trace
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
$env:DEEPSEEK_MODEL = "deepseek-v4-flash"
$env:DEEPSEEK_REASONING_MODEL = "deepseek-v4-flash"

# 可选备用接口
$env:BACKUP_LLM_API_KEY = "替换为备用密钥"
$env:BACKUP_LLM_BASE_URL = "https://example.com/v1"
$env:BACKUP_LLM_MODEL = "model-id"
$env:BACKUP_LLM_REASONING_MODEL = "reasoning-model-id"
```

密钥只放在环境变量或服务器的私密环境文件中，不要提交到 Git。
DeepSeek V4 Flash 同时支持普通对话和深度思考；模型环境变量是可选覆盖项，未设置时也会使用该默认模型。

### 3. 构建界面并启动

```powershell
Set-Location web
npm install
npm run build
Set-Location ..

uv run python server.py
```

浏览器访问 `http://127.0.0.1:8081`。FastAPI 会直接托管 `web/dist`，生产环境不需要再暴露 Vite 的 3000 端口。

应用在 FastAPI lifespan 启动阶段会自动执行等价于 `alembic upgrade head` 的迁移，并在迁移成功后才接受请求。也可以在启动前显式升级；当前 Alembic head 为 `0005_support_quality_loop`：

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

已识别的 pre-Alembic SQLite 会保留现有数据并升级；无法安全识别的部分 schema 会拒绝启动，不会猜测性修改。生产数据库降级前应先停服务并备份，降级不会在启动时自动执行。

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
| `DB_URL` | `sqlite:///./data/ragent-v4-flash.db` | SQLAlchemy 数据库地址；旧 `ragent.db` 会保留但不会被默认覆盖 |
| `API_PREFIX` | `/api/v1` | API 统一前缀 |
| `CORS_ORIGINS` | `http://localhost:3000` | 逗号分隔的跨域来源 |
| `RETRIEVAL_TIMEOUT_SECONDS` | `8` | 检索通道超时 |
| `RETRIEVAL_CANDIDATE_LIMIT` | `20` | 融合前候选数 |
| `RETRIEVAL_CONTEXT_LIMIT` | `6` | 进入 Prompt 的上下文数 |
| `CHAT_TIMEOUT_SECONDS` | `120` | 模型调用超时 |
| `CHAT_FIRST_TOKEN_TIMEOUT_SECONDS` | `20` | 流式生成首 Token 超时 |
| `CHAT_IDLE_TIMEOUT_SECONDS` | `30` | 流式生成 Token 间最大空闲时间 |
| `MAX_UPLOAD_FILE_SIZE` | `52428800` | 服务端允许的单文件最大字节数 |
| `DEEPSEEK_REASONING_MODEL` | `deepseek-v4-flash` | 开启深度思考时使用的 DeepSeek 模型 |
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

## 本地演示数据

项目内置一个可离线、可重复创建的商家售后演示目录。演示用户名固定为 `merchant-demo`，密码不在仓库中且至少需要 10 个字符。非交互运行应通过本机环境变量 `DEMO_SEED_PASSWORD` 提供；未设置时 CLI 会安全地交互提示。以下命令可以直接从仓库根目录复制执行：

```powershell
$env:DEMO_SEED_PASSWORD = "请在本机设置至少10位密码"
.\.venv\Scripts\python.exe -m app.cli seed-demo --reset
.\.venv\Scripts\python.exe -m app.cli seed-demo
```

`seed-demo --reset` 先清理带有 demo 所有权标记的数据再重建；普通用户数据不在清理边界内。再次执行 `seed-demo` 会复用同一用户、知识库、12 份文档、两份交易快照、360 条客服案例、评测集、50 个评测用例和演示会话。密码仅用于本次 seed 的哈希输入，命令输出不会显示密码。

如需只清理演示数据，非交互环境必须显式确认：

```powershell
.\.venv\Scripts\python.exe -m app.cli clear-demo --yes
```

演示知识库固定包含 12 份项目原创摘要/决策表，并在数据库记录来源、适用范围、排除项、复核日期和 provenance；核心来源包括：

- 国家市场监督管理总局的[《网络购买商品七日无理由退货暂行办法》页面](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/art_26ca8fe29e184edd899fa0a7a060d935.html)：项目原创简短摘要；
- 国家市场监督管理总局的[《中华人民共和国消费者权益保护法实施条例》页面](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2024/art_0aea188276a44f0baf940ab95ee00e0a.html)：项目原创简短摘要；
- 全国人大《电子商务法》、市场监管总局食品安全法规库的项目原创主题摘要；
- 两份虚构商家 SOP，明确标记为 `synthetic`，不冒充法律或真实商家承诺。

十份 `public_summary` 均保存官方 URL、发布方、检索日期和用途说明；仓库内容不是官方页面副本，如有差异以官方原文为准。seed/reset 全程读取本地文件，不需要联网；已配置的本地 BGE 模型与 Milvus Lite 会建立持久化向量索引。

### AI 客服质量闭环演示

新工作台围绕一个可落地场景组织：即时零售商家处理配送、退款、促销、商品和食品安全咨询，AI 只能基于当前已发布知识版本提出草稿，人工审核后才会发送。质检失败会聚合成知识缺口，候选版本必须通过固定评测集和高风险门禁才能启用。

首次运行可直接复制：

```powershell
$env:DB_URL = "sqlite:///./data/ragent-v4-flash.db"
$env:DEMO_SEED_PASSWORD = "AdminDemo@2026"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.cli seed-demo --reset
.\.venv\Scripts\python.exe -m app.cli create-admin --username support-admin --password "AdminDemo@2026"
.\.venv\Scripts\python.exe server.py
```

访问 `http://127.0.0.1:8081/login`，使用 `merchant-demo / AdminDemo@2026`。建议按“数据来源 → 即时零售运营 → 客服工作台 → 质量与缺口 → 知识发布 → 上线前评测”的顺序演示。数据包含 360 个来源关联案例、50 个固定评测用例、人工回复决策和 3 个知识缺口；报告明确标注 demo provenance。

仓库默认发现 `models/bge-small-zh-v1.5` 后启用本地 Embedding，并把向量写入 `data/milvus-ragent.db`；`VECTOR_BACKEND=memory` 可显式切换为测试内存模式。模型不可用时关键词检索和人工工作台仍可运行。Milvus Lite 用于本地演示；生产环境应在有足够磁盘的 Linux 主机上部署 Milvus Standalone。

## 当前阶段的能力边界

当前 Agent 运行时采用 LangGraph 的有界 Planner → Tools → Evidence Reviewer 状态图。知识、交易、客服工具均通过 Pydantic 注册表校验；证据不足会携带上轮计划、观察和错误重新调用 Planner，而不是原样重复检索。所有工具均为只读并强制商家所有权范围；联网搜索只在配置真实 `YDC_API_KEY` 后才应注册，当前不展示不可用的假功能。

### Agent Eval 质量门禁

“上线前评测”会逐条运行与聊天主链相同的 Agent Runtime，并保存运行模式、终止状态、工具调用、证据 ID、轨迹和耗时。参考答案不会传给 Agent，也不会被复制为生成答案，只参与人工比对；确定性评分包括预期要点覆盖、预期证据召回、引用正确性、回答 groundedness、拒答/升级正确性和延迟。食品安全、伪造凭证等强制拒答用例失败时，上线审批直接被门禁阻断。

接口演示顺序：

1. 在“知识发布”选择已发布候选版本。
2. 调用 `POST /api/v1/support/evaluations`，请求体为 `{"releaseId": <版本ID>}`。
3. 用 `GET /api/v1/support/evaluations/{runId}` 查看每条用例的 `runtimeMode`、`tools`、`evidenceIds`、`metrics` 与 `trace`。
4. 只有 `highRiskFailures=0` 时，才可通过 `POST /api/v1/support/release-decisions` 批准同一个知识版本。

`deterministic_fallback` 表示没有调用模型服务的离线可复现运行，只能证明工具、轨迹、规则评分和门禁链路正确，不能当作模型质量成绩；`model_backed` 才表示配置模型后的真实生成运行。两种结果在报告中分开显示。当前评分版本为 `agent-eval-v1`，属于保守、可复现的规则评分；尚未加入 LLM-as-judge。知识图谱、写操作工具和自动执行高风险运营动作仍不在本阶段范围内。

## 测试

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

这是 canonical 本地验证命令，可从任意工作目录通过脚本绝对路径调用。它依次执行 Python 编译、后端 pytest、启用中的前端 API/OpenAPI 契约检查、Vitest、ESLint 和 Vite 生产构建；任一阶段失败都会立即停止并返回非零状态。脚本使用仓库自己的 `.venv` 和 `web` Node 环境，不依赖已经启动的 8081 服务。

只运行后端测试时可使用：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

后端测试使用临时 SQLite 数据库。目前覆盖鉴权、会话、文档入库、检索融合、向量检索、RAG 对话、运行追踪、迁移、演示 seed/reset、评测输入模型和 API 契约。

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
- `docs/superpowers/specs/2026-08-07-merchant-ai-operations-closed-loop-design.md`（批准的总体设计）
- `docs/superpowers/plans/2026-08-07-demo-evaluation-foundation.md`（本阶段实现计划）
- `openspec/changes/establish-demo-evaluation-foundation/`（proposal、design、specs 与 tasks）
