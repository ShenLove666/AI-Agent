<h1 align="center">邻里鲜选 AI 运营台</h1>

<p align="center">
  <strong>面向即时零售商家的 Agentic RAG 客服与经营决策平台</strong><br/>
  让 AI 自主判断是否检索知识、查询订单或分析经营数据，并把每条结论追溯到证据。
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img alt="LangGraph" src="https://img.shields.io/badge/Agent-LangGraph-1C3C3C?style=flat-square" />
  <img alt="React" src="https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=111827" />
  <img alt="Milvus" src="https://img.shields.io/badge/Vector-Milvus-00A1EA?style=flat-square" />
  <img alt="Tests" src="https://img.shields.io/badge/quality-tested-16A34A?style=flat-square" />
</p>

<p align="center">
  <img src="assets/agentic-commerce-chat.png" alt="邻里鲜选 Agentic Commerce 对话与经营证据界面" width="100%" />
</p>

## 🚀 这是什么项目？

邻里鲜选不是一个只会回答问题的“知识库聊天框”，而是一套围绕即时零售真实工作流构建的 AI 应用工程项目：

- 顾客咨询退货、履约、促销或食品安全时，Agent 自主选择知识、订单、履约、退款与客服工具。
- 商家询问商品搭配、缺货风险或经营机会时，系统查询隔离后的交易事实并给出可复核依据。
- 回答生成前由 Evidence Reviewer 检查相关性、覆盖度、冲突和高风险缺口，证据不足时受限重规划。
- 每次运行记录计划、工具参数、证据、耗时和终止状态，可进入评测、优化任务和发布门禁。

项目的完整闭环是：

```text
真实/公开数据 → 知识与经营事实 → Agent 自主规划 → 可追溯回答
       ↑                                      ↓
  知识发布 ← 缺口与优化任务 ← 反馈 / Trace / Eval
```

> 本项目以 [nageoffer/ragent](https://github.com/nageoffer/ragent) 为学习与改造起点，重构为 Python / FastAPI 后端，并扩展了即时零售数据、LangGraph Agent、证据审查、客服质量闭环和商家运营工作台。上游项目与本项目的技术实现、业务范围并不相同。

## 🧭 快速导航

| &nbsp; | 入口 | 说明 |
|:---:|:---|:---|
| ⚡ | [快速开始](#quick-start) | 初始化环境、导入演示数据并启动 |
| 🏗️ | [核心设计](#architecture) | Agent、RAG、模型路由和业务工具架构 |
| ✨ | [项目能力](#features) | 已落地的产品与工程能力 |
| 📊 | [数据与可信度](#data) | 数据来源、口径和 provenance |
| 🧪 | [测试与验证](#quality) | 一键验证与覆盖范围 |
| ⚙️ | [配置与部署](#deployment) | 模型、向量库和服务器部署 |
| 📚 | [设计文档](#documents) | 架构、可靠性和演进记录 |

## 💡 为什么要做它？

很多 RAG 项目的链路只有 `Embedding → TopK → LLM`，可以演示，却难以回答真实业务中的几个问题：

1. 用户问的是规则、订单还是经营分析，系统应该查什么？
2. 搜到内容是否真的足够支撑结论，证据冲突怎么办？
3. 模型超时、空回答或供应商故障时，系统如何降级？
4. AI 回答效果如何评测，问题如何回流到知识和产品迭代？
5. 演示数据、衍生指标和真实观测数据如何避免混为一谈？

邻里鲜选把这些问题落到了代码和产品界面里。它更适合作为 **AI Application Engineer / Agent Engineer / RAG Engineer / AI 产品运营** 方向的工程作品，而不是一个框架套壳 Demo。

<a id="architecture"></a>

## 🏗️ 核心设计

### 系统架构

```mermaid
flowchart TD
    UI["React 商家工作台"] --> API["FastAPI API / SSE"]
    API --> AUTH["JWT 与商家所有权隔离"]
    API --> AGENT["LangGraph Agent Runtime"]

    AGENT --> PLAN["Planner"]
    PLAN --> TOOLS["Tool Registry + Pydantic 校验"]
    TOOLS --> KB["Knowledge Search"]
    TOOLS --> COMMERCE["商品 / 购物篮分析"]
    TOOLS --> ORDER["订单 / 履约 / 退款"]
    TOOLS --> SUPPORT["客服案例 / 质量指标"]

    KB --> RETRIEVAL["Keyword + Vector → Weighted RRF → Rerank"]
    RETRIEVAL --> EVIDENCE["Evidence Reviewer"]
    COMMERCE --> EVIDENCE
    ORDER --> EVIDENCE
    SUPPORT --> EVIDENCE
    EVIDENCE -->|"证据不足"| PLAN
    EVIDENCE -->|"证据充分"| ROUTER["LLM Router / Circuit Breaker"]
    ROUTER --> ANSWER["回答 + 引用 + 推荐追问"]
    ANSWER --> OBSERVE["Trace / Feedback / Eval / Quality Gate"]
```

### Agentic RAG 主链路

```text
Question
   ↓
Intent Router ── 意图前置门：直接作答 / 引用历史 / 拒答 / 研究检索
   ├─ direct / history_reference → 无需检索，直答或复用上轮答案
   └─ research → 问题改写 → Planner ── 决定是否调用工具、调用哪个工具
   ↓
Tools ──── knowledge / commerce / order / support
   ↓
Evidence Reviewer ── relevance / coverage / contradiction / authority
   ├─ insufficient → 带观察结果重新规划（有步数与调用预算）
   └─ ready        → 组织可引用上下文
   ↓
Model Router ── 主模型 / 备用模型 / 超时 / 熔断 / 空回答降级
   ↓
SSE Answer ── thinking / response / sources / finish
```

<details>
<summary><b>为什么同时使用 LangGraph 与自研业务模块？</b></summary>

LangGraph 负责有状态编排：`Planner → Tools → Reviewer → Re-plan`。意图路由、检索、模型路由、熔断、会话一致性、数据权限和业务 SQL 仍由项目自己的模块实现。

这种边界避免把所有逻辑堆进一个 Agent Prompt，也避免为了“用了框架”而牺牲可测试性。Planner 不可用时存在确定性 fallback；工具参数由 Pydantic 校验；运行受 `max_steps` 和 `max_tool_calls` 约束，不允许无限循环。

</details>

<details>
<summary><b>意图路由前置层为什么单独成模块？</b></summary>

`ConversationIntentRouter` 在 Planner 之前先判定四类意图：`direct`（如「1+1」直接作答，不污染检索）、`history_reference`（如「那土豆呢」继承上轮语境，不重复检索）、`refuse`（伪造/越权问题明确拒答）与 `research`（业务关键词强制走检索）。快速路径（琐碎直答、短指代、拒答词表、业务关键词）确定性拦截，避免真实模型把「那土豆呢」误分类为历史指代或把「1+1」误送检索；模型路径带 few-shot 并容错解析。

</details>

<details>
<summary><b>混合检索为什么不是简单向量 TopK？</b></summary>

知识检索并发执行关键词与向量通道，使用数据库 Chunk ID 去重，再通过 Weighted RRF 融合不同分值空间。融合结果可以进入 CrossEncoder 重排；重排不可用时保留融合排序，不让整个问答失败。

```text
Keyword ─┐
         ├─ Dedup → Weighted RRF → Optional Rerank → Metadata Enrichment
Vector  ─┘
```

指定知识库时，关键词和向量通道使用同一 Scope；任何单通道异常都不会拖垮完整请求。

</details>

<details>
<summary><b>模型调用如何处理生产故障？</b></summary>

- 多供应商按优先级路由，主模型失败后切换备用模型。
- 区分总超时、首 Token 超时和 Token 间空闲超时。
- 三态熔断器隔离持续故障的供应商，并在恢复窗口后试探。
- 客户端取消会传播到生成任务，避免后台继续消耗模型额度。
- 空回答、异常流和失败消息都有明确状态，不伪装为成功结果。

</details>

<a id="features"></a>

## ✨ 项目能力

### 1. Agent 与可追溯问答

- 意图前置路由：直接作答 / 引用历史语境 / 拒答 / 研究检索，快速路径确定性拦截。
- LangGraph ReAct 查询规划与工具自主路由，执行全程 Timeline 实时进度（规划→工具→审查→生成）。
- 知识、交易、订单、履约、退款、顾客快照和客服案例工具。
- Evidence Reviewer 检查证据相关性、覆盖度、冲突、权威性和高风险字段。
- SSE 流式思考、正文、来源与结束事件；刷新后可恢复完整状态。
- 来源区分知识文档、内部经营数据、观测数据、衍生指标和演示数据。
- 对话导航 rail（Minimap）：每轮一根线，当前轮加深，hover 摘要，点击跳转（长对话采样 40 槽）。
- 点赞、点踩、重新生成、推荐追问与对话版本持久化。

### 2. 知识与检索工程

- 多知识库和商家所有权隔离。
- TXT、Markdown、PDF、DOCX 上传、解析、分块和预览。
- 关键词 + Milvus 向量混合检索、Weighted RRF、可选 Rerank。
- 已发布知识版本、候选版本、知识缺口和上线前评测。
- 本地 `BGE-small-zh-v1.5` Embedding，输出 512 维向量。

### 3. 即时零售运营

- 购物篮支持度、置信度、提升度与共现次数计算。
- 关联规则筛选、排序、证据下钻和搭配购方案创建。
- 商品、订单、履约、退款和顾客历史上下文。
- AI 工具渗透率、回答好评率、知识命中率和高频意图分析。
- 运营问题转化为优化任务、周报与可审计动作。

### 4. 客服质量闭环

- 工单队列、会话区、订单上下文和 AI Copilot 三栏工作台。
- AI 只生成建议草稿；人工确认后才能模拟或真实外发。
- Copilot 检索严格限定已发布知识版本（无发布版本时只依据订单/履约/退款事实作答）。
- 草稿由已核实事实驱动：核对订单/履约/退款状态，无送达时点不承诺具体时间，不引用证据原文。
- 风险门禁：高风险建议禁止直发（必须升级主管），中风险需人工勾选确认事实与规则。
- 负反馈、知识未命中、慢响应和失败运行聚合为知识缺口。
- 固定评测集覆盖 retrieval、reasoning、refusal、multi-tool 与高风险场景。
- 高风险用例失败会阻止候选知识版本上线。

### 5. 工程可靠性

| 能力 | 实现 |
|:---|:---|
| 请求一致性 | requestId 指纹、处理中拒绝重复、成功结果回放、失败可安全重试 |
| 会话一致性 | Turn / Message 状态机、版本化回答、异常历史过滤、取消不写成功缓存 |
| 模型容错 | 多候选路由、三态熔断、首包/空闲/总超时、空响应 fallback |
| 数据安全 | JWT、商家所有权过滤、上传类型和大小校验、工具参数校验 |
| 可观测性 | Trace Run / Node、工具调用、证据 ID、耗时、终止状态与错误码 |
| 数据迁移 | Alembic 自动升级、旧 SQLite 安全识别、未知 schema fail closed |
| 外发安全 | 人工确认、审计记录、Demo 模拟发送、生产 HMAC Webhook |

<a id="data"></a>

## 📊 数据与可信度

项目不把所有数据都包装成“真实业务数据”，而是显式记录 lineage 与 provenance：

| 数据 | 规模 | 类型 | 用途 |
|:---|---:|:---|:---|
| 用户授权购物篮快照 | 9,835 个匿名购物篮、43,367 条商品出现记录 | `observed` | 商品共现和关联规则 |
| UCI Online Retail II 固定快照 | 5,000 条公开交易 | `observed` | 时间、数量、单价、国家和取消标记分析 |
| 关联规则与经营指标 | 基于交易确定性计算 | `derived` | 搭配建议与证据下钻 |
| 商家售后知识 | 12 份原创摘要/决策表 | `public_summary` / `synthetic` | 退货、消费者权益、食品安全与商家 SOP |
| 客服案例 | 360 条来源关联案例 | `synthetic` / grounded demo | 客服工作台和质量运营 |
| Agent 评测 | 50 个固定用例 | `evaluation_only` | 上线门禁，不进入 Agent 输入 |

授权原始目录只读，仓库保存确定性 gzip 快照和 SHA256 清单。公开法规只保存项目原创摘要、官方 URL、发布方、检索日期与适用范围，不复制官方全文。演示商家 SOP 明确标记为虚构内容，不能冒充真实商家承诺。

> 购物篮数据不含当前价格、库存、活动和门店信息。因此系统可以说明历史共现关系，但不能承诺实际优惠或实时可售。

## 🖥️ 产品工作台

| 页面 | 主要用途 |
|:---|:---|
| AI 对话 | Agent 自主选工具、意图路由、流式回答、执行 Timeline、证据侧栏、对话导航 rail、反馈与追问 |
| 客服工作台 | 工单、会话、订单/顾客上下文、AI 处理建议（事实/规则/风险）、人工确认（三栏工作区） |
| 主管队列 | 升级单接管、风险决策（批准/要求证据/转专员/退回） |
| 商品组合洞察 | 关联规则、运营方案（草稿→确认→发布）、优化任务闭环 |
| 知识发布 | 来源管理、候选版本、发布记录和回滚依据 |
| 质量与缺口 | 负反馈、未命中、高风险问题与优化任务 |
| 上线前评测 | Agent Trace、指标、用例明细和高风险门禁 |
| 运行追踪 | Planner、工具、Reviewer、生成节点及耗时瀑布图（技术细节深色面板） |

> 界面遵循 **light-first 设计系统**：业务事实为浅色区域，AI 判断模块用极浅靛蓝背景 + AI 徽标建立辨识度；深色面板仅用于 Trace / Tool Call / JSON 等技术执行细节。

<a id="quick-start"></a>

## ⚡ 快速开始

环境要求：

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 18+
- Windows PowerShell（本文命令）

### 已完成初始化：一条命令启动

```powershell
$env:VECTOR_BACKEND = "disabled"   # 未配置向量模型时必须关闭（见"配置与部署"）
.\.venv\Scripts\python.exe server.py
```

打开 `http://127.0.0.1:8081/login`。

| 账号 | 角色 | 默认密码 | 数据范围 |
|:---|:---|:---|:---|
| `admin` / `support-admin` | 管理员 | `AdminDemo@2026` | 全部页面（知识库、设置、用户、评测、Dashboard） |
| `merchant-demo` | 管理员（商家 owner） | `AdminDemo@2026` | 演示商家全部数据 |
| `demo-supervisor` | 客服主管 | `AdminDemo@2026` | 主管队列、质量与缺口、客服运营报告 |
| `demo-operator` | 商家运营 | `AdminDemo@2026` | 商品组合洞察、运营方案、用户管理 |
| `demo-agent` | 客服 | `AdminDemo@2026` | 客服工作台 |

> 上表账号仅用于本地演示。任何共享环境或公网部署都必须删除或停用演示账号、修改密码，并显式设置随机 `JWT_SECRET`；不要把演示凭据当作生产凭据。

> 权限模型为 **4 角色 RBAC**（user / supervisor / operator / admin）：角色 → 权限 → API 三层校验。前端菜单只是展示层，后端每个端点按权限依赖硬性拦截；数据范围由组织成员关系限定，跨组织资源统一返回 404（不暴露存在性）。

### 首次完整初始化

```powershell
uv venv .venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements-dev.txt

Set-Location web
npm install
npm run build
Set-Location ..

.\.venv\Scripts\python.exe scripts\setup_local_ai.py
$env:DEMO_SEED_PASSWORD = "AdminDemo@2026"
.\.venv\Scripts\python.exe -m app.cli seed-demo --reset
.\.venv\Scripts\python.exe -m app.cli create-admin --username support-admin --password "AdminDemo@2026"
.\.venv\Scripts\python.exe server.py
```

日常启动不需要重复执行 `npm install`、`npm run build` 或 `seed-demo`。

### 配置 DeepSeek

```powershell
$env:DEEPSEEK_API_KEY = "替换为自己的密钥"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
$env:DEEPSEEK_MODEL = "deepseek-v4-flash"
$env:DEEPSEEK_REASONING_MODEL = "deepseek-v4-flash"
```

密钥只应放在环境变量或服务器私密环境文件中，不要提交到 Git。可从仓库根目录的
`.env.example` 复制一份本地 `.env`，再逐项填写；`.env.example` 不包含任何可用密钥。

### 开发模式

```powershell
# 终端 1：后端
$env:VECTOR_BACKEND = "disabled"
.\.venv\Scripts\python.exe server.py

# 终端 2：前端热更新
Set-Location web
npm run dev
```

访问 `http://127.0.0.1:5173`；Vite 会把 `/api` 代理到 8081。生产构建由 FastAPI 直接托管 `web/dist`。

<a id="deployment"></a>

## ⚙️ 配置与部署

### 检索模式

#### 本地 Embedding + Milvus Lite（默认演示）

仓库发现 `models/bge-small-zh-v1.5` 后启用本地 Embedding，并将向量持久化到 `data/milvus-ragent.db`。首次下载与检查：

```powershell
.\.venv\Scripts\python.exe scripts\setup_local_ai.py
```

#### 内存向量库（测试）

```powershell
$env:VECTOR_BACKEND = "memory"
$env:EMBED_MODEL_PATH = "D:\models\bge-small-zh-v1.5"
$env:EMBED_DIMENSION = "512"
```

服务重启后需要重新建立内存索引。

#### Milvus Standalone（服务器）

```powershell
$env:VECTOR_BACKEND = "milvus"
$env:MILVUS_URI = "http://127.0.0.1:19530"
$env:MILVUS_COLLECTION = "ragent_chunks_v2"
```

Milvus Lite 适合单机演示；生产环境建议使用有持久化磁盘、备份和监控的 Milvus Standalone。

#### 仅关键词模式（无向量依赖）

```powershell
$env:VECTOR_BACKEND = "disabled"   # 或 none / off
```

该模式适合接口联调与无模型环境。知识库仍可走关键词检索，经营 SQL 工具不受影响。**注意**：`VECTOR_BACKEND` 默认 `milvus`，环境未配置 Embedding 模型或 Milvus 时首次向量检索可能触发底层崩溃（libarrow segfault），服务器部署务必显式设为 `disabled`。

### 常用环境变量

| 环境变量 | 默认值 | 说明 |
|:---|:---|:---|
| `DB_URL` | `sqlite:///./data/ragent-v4-flash.db` | SQLAlchemy 数据库地址 |
| `API_PREFIX` | `/api/v1` | API 前缀 |
| `CORS_ORIGINS` | `http://localhost:3000`（代码兼容默认） | 本地 Vite 使用 5173 时请在 `.env` 中显式改为 `http://localhost:5173`；生产只列真实 HTTPS 来源 |
| `JWT_SECRET` | 内置占位值（不安全） | 共享/生产环境必须注入随机密钥；应用不会替你轮换密钥 |
| `JWT_EXPIRE_MINUTES` | `43200`（30 天，代码兼容默认） | 生产建议显式设为 `720`（12 小时）或更短 |
| `VECTOR_BACKEND` | `milvus` | `milvus`（Milvus Lite/Standalone）、`memory`（内存索引）或 `disabled`（仅关键词） |
| `EMBED_MODEL_PATH` | 项目内 BGE 路径 | 本地 Embedding 模型目录 |
| `EMBED_DIMENSION` | `512` | 必须与模型输出维度一致 |
| `RETRIEVAL_CANDIDATE_LIMIT` | `20` | 融合前候选数 |
| `RETRIEVAL_CONTEXT_LIMIT` | `6` | 进入 Prompt 的上下文数 |
| `CHAT_FIRST_TOKEN_TIMEOUT_SECONDS` | `20` | 首 Token 超时 |
| `CHAT_IDLE_TIMEOUT_SECONDS` | `30` | Token 间空闲超时 |
| `CHAT_TIMEOUT_SECONDS` | `120` | 总生成超时 |
| `MAX_UPLOAD_FILE_SIZE` | `52428800` | 单文件最大字节数 |
| `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY` | 未设置 | 模型端点密钥（按优先级 failover：DashScope → DeepSeek → 备用） |
| `VISION_MODEL` | `qwen3.7-plus` | 识图 / 对话默认模型 |
| `CUSTOMER_CHANNEL` | `demo` | `demo` 模拟发送；`webhook` 调外部渠道 |
| `CUSTOMER_WEBHOOK_URL` | 未设置 | 生产 Webhook HTTPS 地址 |
| `CUSTOMER_WEBHOOK_SECRET` | 未设置 | HMAC-SHA256 密钥 |

### 数据迁移

应用启动时会自动执行等价于 `alembic upgrade head` 的迁移，迁移成功后才接受请求。也可显式执行：

```powershell
$env:DB_URL = "sqlite:///./data/ragent-v4-flash.db"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

当前迁移 head 为 `0016_optimization_verification_runs`。已识别的旧 SQLite 会保留数据并升级；无法安全识别的 schema 会拒绝启动，而不是猜测性修改。

### 服务器部署

服务默认监听 `0.0.0.0:8081`，这是开发/内网端口，不应直接暴露公网。生产必须由 Nginx/Caddy 在 `443` 终止 TLS，反向代理到仅监听回环地址的 `127.0.0.1:8081`，并在防火墙中拒绝公网访问 8081；前后端应使用同一 HTTPS 入口，避免登录、SSE 或来源预览跳到错误端口。

一键部署（本地执行，tar 同步 + 按端口重启 + 健康检查）适合演示/单机预览，不是完整生产发布系统：

```bash
bash scripts/deploy.sh [目标目录]   # 默认 rag-project-<version>
```

- 同步时**排除 `.env` / `data/` / `*.db` / `node_modules` 等**，服务器私密配置与数据库不受覆盖
- 新版本目录软链接旧 `.venv` 复用依赖；`VECTOR_BACKEND=disabled` 必须写入服务器 `.env`
- 脚本不会自动备份数据库、执行回滚、安装依赖或托管进程；生产请在 systemd/Supervisor 下运行，并在切换前做可验证的数据库备份
- 公开部署前必须配置 HTTPS、随机 JWT 密钥、非演示账号、日志轮转和告警；不要把脚本的 8081 端口直接暴露给互联网
- 详细流程与踩坑记录见 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)

部署时至少持久化：

- `data/`：SQLite、Milvus Lite 与演示数据；
- `models/`：本地 Embedding / Rerank 模型；
- 私密环境文件：模型 API 密钥与 Webhook 密钥。

<a id="quality"></a>

## 🧪 测试与验证

从仓库根目录运行完整验证：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

验证顺序包括：

1. Python 编译检查；
2. 后端 pytest；
3. 前端 API / OpenAPI 契约检查；
4. Vitest；
5. TypeScript 类型检查；
6. ESLint；
7. Vite 生产构建。

任一阶段失败会立即停止并传递真实退出码。脚本使用项目自己的 `.venv` 和 `web` 环境，不依赖已启动的 8081 服务。

当前 `main` 基线验证结果为后端 252 个收集用例（250 passed、2 个环境相关 skip）和前端 303 个通过用例；同一组门禁也在
`.github/workflows/ci.yml` 的每次 push/PR 中运行。

单独运行：

```powershell
# 后端
.\.venv\Scripts\python.exe -m pytest -q

# 前端
Set-Location web
npm test
npm run lint
npm run build
```

测试覆盖鉴权、租户隔离、会话状态、文档入库、检索融合、向量检索、Agent 工具、证据审查、SSE、取消与超时、模型路由、迁移、演示数据幂等、客服闭环、评测门禁和前端关键交互。

重点测试：

| 文件 | 覆盖 |
|:---|:---|
| `tests/test_rbac_matrix.py` | 完整越权矩阵：11 个代表性 API × 4 角色（200/403）+ 跨组织资源 404 |
| `tests/test_intent_router.py` | 意图路由：直答/历史指代/拒答/研究，配对回归（Case A「1+1」不被牛肉污染、Case B「那土豆呢」继承语境） |
| `tests/test_support_escalation.py` | 升级生命周期状态机（接管/决议/退回/转交） |
| `tests/test_reply_review.py` | AI 回复审核闭环（采纳/修订/升级） |
| `tests/test_support_copilot_gates.py` | Copilot 风险门禁：高/中/低风险发送控制、release 限定检索 |
| `tests/test_migrations.py` | 迁移链一致性（0001 → 0016） |

## ⚠️ 当前能力边界

- 当前是可实际运行的单机/作品集系统，不等同于完成容量规划与合规认证的企业 SaaS。
- 联网搜索尚未接入当前 Agent Runtime；页面不展示不可用的假功能。
- Agent 业务工具默认只读；高风险外发和运营动作必须人工确认。
- `deterministic_fallback` 只能证明工具、轨迹和门禁链路可复现，不能作为真实模型质量成绩。
- 当前 groundedness 是确定性保守评分，尚未替代完整的 claim-level LLM-as-judge。
- 知识图谱、多 Agent 群聊和自动执行高风险业务动作不在当前 MVP 范围。
- SQLite 与 Milvus Lite 适合单机演示；生产多实例需要外部数据库、Milvus Standalone、备份和可观测基础设施。

<a id="documents"></a>

## 📚 设计文档

| 文档 | 内容 |
|:---|:---|
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | **用户操作手册**：4 角色操作流程、权限矩阵、客服/主管/运营/管理全流程 |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | **搭建部署与实现原理手册**：环境、配置、数据导入、服务器部署、全链路实现 |
| [`docs/python-ragent-architecture.md`](docs/python-ragent-architecture.md) | Python 重构架构与模块边界 |
| [`docs/production-rag-reliability.md`](docs/production-rag-reliability.md) | 流式输出、超时、取消和模型容错 |
| [`docs/chat-product-completeness.md`](docs/chat-product-completeness.md) | 对话产品完整性审计 |
| [`docs/jd-alignment-ai-product-operations.md`](docs/jd-alignment-ai-product-operations.md) | 与 AI 产品运营 JD 的能力映射 |
| [`docs/v2.1-state-and-retrieval-scope.md`](docs/v2.1-state-and-retrieval-scope.md) | 会话状态与检索范围一致性 |
| [`docs/v2.2-pre-turn-consistency.md`](docs/v2.2-pre-turn-consistency.md) | Turn 创建与失败恢复 |
| [`docs/implementation-gap-audit.md`](docs/implementation-gap-audit.md) | 实现缺口与非目标审计 |

## 🤝 致谢

- [nageoffer/ragent](https://github.com/nageoffer/ragent)：项目最初的产品界面、RAG 工程方向与学习参考。
- [LangGraph](https://github.com/langchain-ai/langgraph)：有状态 Agent 编排。
- [Milvus](https://github.com/milvus-io/milvus)：向量检索基础设施。
- [FastAPI](https://github.com/fastapi/fastapi) 与 [React](https://github.com/facebook/react)：应用后端与前端基础。

如果你在阅读这个项目，建议从 `app/modules/rag/`、`app/modules/retrieval/`、`app/modules/evaluation/` 和 `web/src/pages/admin/` 开始，再结合 Trace 与评测页面理解完整闭环。
