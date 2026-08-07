# RAGent Python 实现差距与整改清单

> 用途：可直接交给其他 AI 或开发人员执行。
> 审计基线：当前 `D:\Project\rag-project`，前端来自 `D:\Project\ragent\frontend`，后端为 Python/FastAPI。
> 核心约束：保留 RAGent 原版 UI，不自行改版；后端继续使用 Python；不能用静态假数据冒充已实现接口。

## 阶段 A 执行进度（2026-08-06 更新）

已完成并验证（12/12 测试通过）：

- [x] **P0-4 权限闭环**: `require_admin` 依赖、管理接口全部强制 admin（普通用户 403）、越权测试
- [x] **P0-3 管理员初始化**: `uv run python -m app.cli create-admin --username admin --password xxx`
- [x] **P0-2 知识库 Compatibility API** (`app/api/compat_knowledge.py`, 单数 `/knowledge-base`):
  库 CRUD+分页 / 文档分页/上传/搜索/删除/启停/重新切块/预览/下载 / Chunk 分页/增删改/批量启停 / chunk-logs / ingestion-spec-schema
- [x] **P0-5 停止生成**: `ChatTaskRegistry` (进程内) + `/rag/v3/stop` 接入 `/rag/v3/chat` 流, 中断发送 `INTERRUPTED`
- [x] **消息反馈与推荐问题**: `/conversations/messages/{id}/feedback` (POST/DELETE, Message.vote 列 + 轻量迁移), `recommended-questions`
- [x] **Trace Compatibility** (`app/api/compat_trace.py`): `/rag/traces/runs` 分页契约 (admin)
- [x] **用户管理**: `/users` CRUD + `/user/password` (admin 管理, 本人改密)
- [x] **501 兜底**: agents / dashboard / biz-change-logs / ingestion / intent-tree / kg / mappings / sample-questions 返回结构化 `NOT_IMPLEMENTED`
- [x] **会话契约补全**: conversations 响应增加 `conversationId/lastTime`, 消息增加 `sources/messageStatus/vote/createTime` (兼容旧字段)
- [x] **契约测试**: `tests/test_compat_contracts.py` (4 个: 知识库全链路 / 用户管理与越权 / Trace+反馈+停止 / 前端 service 根路径契约探测)

未完成 (后续阶段): 持久化任务队列 (P1-7)、多轮历史进生成 (P1-3)、token budget (P1-4)、Embedding API (P1-5)、
Alembic 迁移 (P1-10)、Playwright E2E、真实 Milvus 集成测试、前端依赖安全与分包 (P2-2)。

> 注意: 阶段 A 验收"所有菜单都能打开"仍依赖前端实际联调——当前 501 模块返回结构化错误,
> UI 会显示明确提示但功能未实现。下一轮建议: 前端浏览器联调 + Playwright E2E。

## 一、当前真实状态

当前项目不是完整的 RAGent Python 复刻，而是以下组合：

- RAGent 原版 React/TypeScript/Tailwind 前端已经整体迁入；
- Python 后端实现了用户、会话、基础知识库、基础入库、关键词/可选向量检索、RAG 对话和简化 Trace；
- 通过少量兼容代码接通了登录、会话和 RAGent GET-SSE 对话；
- RAGent 管理后台的大多数业务接口仍不存在；
- 当前测试主要验证 Python 核心模块，尚未覆盖完整前后端契约和浏览器操作。

因此，项目目前更适合作为开发骨架，不应描述为“功能完整的 RAGent Python 版”。

## 二、P0：阻断核心使用的问题

### P0-1 前后端 API 契约大面积不一致

后端目前只有约 20 个路由，前端仍会调用大量 RAGent 原接口。以下前端模块没有对应的 Python 后端实现，页面打开后会出现 404、空白、错误 Toast 或无法提交：

| 前端功能 | 前端接口族 | 当前状态 |
|---|---|---|
| 管理首页 | `/admin/dashboard/*` | 未实现 |
| Agent 管理 | `/agents/*` | 未实现 |
| 业务变更日志 | `/biz-change-logs/*` | 未实现 |
| 摄取管道与任务 | `/ingestion/pipelines/*`、`/ingestion/tasks/*` | 仅有内部 pipeline 类，没有 API、表和任务系统 |
| 意图树 | `/intent-tree/*` | 未实现 |
| 知识图谱 | `/admin/kg/*` | 未实现 |
| 查询词映射 | `/mappings/*` | 未实现 |
| 示例问题 | `/rag/sample-questions`、`/sample-questions/*` | 未实现 |
| 用户管理 | `/users/*`、`/user/password` | 未实现 |
| 系统设置 | `/rag/settings` | 只有只读简化接口 `/management/settings`，契约不一致 |
| RAG Trace | `/rag/traces/runs/*` | 后端为 `/management/traces/*`，字段与分页契约不一致 |
| 反馈/推荐问题/停止生成 | `/conversations/messages/*`、`/rag/v3/stop` | 未实现 |
| 文档预览与源文件 | `/knowledge-base/docs/{id}/preview|file` | 未实现 |
| Chunk 增删改启停 | `/knowledge-base/docs/{id}/chunks/*` | 未实现 |

执行要求：

1. 从 `web/src/services/*.ts` 自动提取接口清单，生成契约测试；
2. 优先在 Python 后端实现 RAGent 契约，不修改页面来隐藏功能；
3. 对确定暂不实现的模块返回结构化 `501 NOT_IMPLEMENTED`，同时在 UI 保持原布局并显示明确状态；
4. 禁止返回静态统计数字、假 Trace、假任务记录来让页面“看起来能用”。

验收标准：

- 所有前端 service 请求至少有明确的 2xx/4xx/501 契约，不出现未知 404；
- 建立自动化契约测试，覆盖每个 service 导出的函数；
- 浏览器控制台无未处理 Promise rejection。

### P0-2 知识库页面与后端路径、字段完全不一致

Python 后端使用：

- `/knowledge-bases`
- `/knowledge-bases/{id}/documents`
- 字段：`knowledgeBaseId`、`filename`、`fileSize`、`createdAt`

RAGent 前端使用：

- `/knowledge-base`
- `/knowledge-base/{id}/docs`
- 字段：`kbId`、`docName`、`chunkCount`、`createTime` 等

当前 `knowledgeService.ts` 基本仍是 Java 后端契约，因此管理后台知识库功能并未真正接通。

执行要求：优先新增 Python 的 RAGent Compatibility Router，完整实现前端已有契约，内部再调用现有 KnowledgeService；不要在多个页面中散落字段转换。

必须实现：

- 知识库分页、详情、创建、重命名、删除；
- 文档分页、详情、上传、删除、启停、重新切块；
- Chunk 分页、创建、编辑、删除、批量启停；
- 文档原文件下载和安全预览；
- 入库配置 schema 与入库日志。

### P0-3 用户无法通过当前 RAGent 登录页注册

后端有 `/auth/register`，RAGent 原登录页只提供登录。新环境没有预置用户时，用户无法从 UI 进入系统。

执行方案二选一，并保持 RAGent 设计：

- 增加符合 RAGent 视觉体系的注册入口；或
- 提供首次启动管理员初始化命令，例如 `uv run python -m app.cli create-admin`。

不要把所有注册用户默认设为管理员。

### P0-4 管理员权限链路不完整

前端根据 `user.role === "admin"` 控制后台访问，但后端目前：

- 注册请求不能指定角色；
- 没有管理员创建/修改用户接口；
- 管理接口只检查“已登录”，没有检查 admin；
- 知识库当前按 owner 隔离，与 RAGent 的后台管理语义尚未统一。

执行要求：

- 增加 `require_admin` 依赖；
- 所有 `/admin`、用户管理、系统配置、全局 Trace 接口必须强制管理员权限；
- 明确普通用户能否创建私有知识库；
- 增加越权测试：普通用户不可读写他人的会话、知识库、文档、Trace。

### P0-5 流式错误处理仍不可靠

之前“三个点一直动”的直接原因已修复：MiMo 默认输出 `reasoning_content`，当前配置关闭 thinking 后输出普通 content。但仍存在：

- SSE 响应开始后发生模型异常时，没有稳定地发送 `event:error` 和 `event:done`；
- 浏览器断开后，后端没有显式取消上游模型请求；
- RAGent 的停止生成接口尚未实现；
- Compatibility SSE 使用临时 `taskId`，没有真正任务注册表；
- `finish` 没有返回持久化后的 messageId；
- 重试可能造成同一个问题重复写入数据库；
- Query Rewrite 与 Answer 共用模型，改写阶段可能造成首 Token 延迟。

执行要求：

- 建立 ChatTaskRegistry，保存 taskId、取消事件、用户、会话和状态；
- 实现 `/rag/v3/stop`；
- 捕获模型、检索和数据库异常并发送规范 SSE 终止事件；
- 监听 `request.is_disconnected()` 并取消上游流；
- 使用幂等 requestId，防止重试重复消息；
- `finish` 返回真实 messageId、sources、messageStatus；
- 增加断连、取消、供应商超时、半途中断的测试。

## 三、P1：已实现但存在明显缺陷

### P1-1 MiMo 配置命名混乱

聊天目前复用了识图变量：`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`VISION_MODEL`。虽然能运行，但职责混乱，后续切换视觉模型会意外改变聊天模型。

整改：

- 聊天只读取 `MIMO_API_KEY`、`MIMO_BASE_URL`、`MIMO_CHAT_MODEL`；
- 视觉只读取 `VISION_API_KEY`、`VISION_BASE_URL`、`VISION_MODEL`；
- 可为旧变量提供一次性兼容并输出弃用警告；
- 提供不含密钥的 `.env.example`；
- 启动日志只输出 provider/model/base host，不输出 Key。

### P1-2 Query Rewrite 对 MiMo 发起额外调用，成本和延迟偏高

每轮对话先调用模型改写，再调用模型生成。没有知识库或查询很清晰时，这次调用意义不大。

整改：

- 无知识库、关闭 RAG、短问候、明确命令时跳过改写；
- 改写使用更小、更快的模型或规则；
- 缓存相同会话上下文下的改写结果；
- Trace 中分别记录 rewrite TTFT、token、费用和 fallback 原因。

### P1-3 对话没有真正使用多轮历史生成回答

当前历史消息只用于 Query Rewrite，最终 ModelChatRequest 只包含 system + 当前 user，没有把历史对话加入生成请求。多轮追问可能丢失上下文。

整改：

- 将最近 N 轮消息加入生成上下文；
- 超出预算后采用 token-aware 截断或摘要；
- 历史、知识库上下文、系统提示分别设置预算；
- 增加“它/这个方案/上一条”等指代追问测试。

### P1-4 检索参数没有完整生效

配置中有 candidate/context limit，但需要核查它们是否贯穿所有通道、融合和 Prompt 构造。当前 Prompt 构造会直接拼接 retrieval 返回结果，缺少严格 token 预算。

整改：

- candidate limit 用于各通道初筛；
- context limit 用于融合/重排后的最终结果；
- 增加基于 tokenizer 的上下文 token budget；
- 对超长 Chunk 截断并保留来源定位；
- Trace 记录各阶段输入/输出数量。

### P1-5 默认轻量模式只有关键词检索，质量有限

未配置 `EMBED_MODEL_PATH` 时只有 jieba 关键词检索。它适合联调，不适合作为完整 RAG 的默认生产方案。

整改建议：

- 支持 OpenAI-compatible Embedding API，避免必须下载本地模型；
- 默认可选小模型，例如 `bge-small-zh-v1.5`，不要强制 BGE-M3；
- 明确不同 embedding 模型不能复用同一 collection；
- collection metadata 记录模型 ID、维度、归一化方式和版本；
- 模型变更时阻止混写并提供重建索引任务。

### P1-6 InMemoryVectorStore 重启即丢失

SQL 中 Chunk 仍在，但内存向量消失，重启后向量检索无结果；当前没有启动时自动恢复索引机制。

整改：开发环境明确标注临时；生产默认使用 Milvus/Qdrant/pgvector 之一；增加索引一致性检查和重建命令。

### P1-7 文档入库任务不可靠

上传后使用 FastAPI BackgroundTasks。它没有持久任务队列，进程重启或崩溃会丢任务；没有重试、进度、租约、并发限制和死信状态。

整改：

- 建立 `ingestion_tasks`、`ingestion_task_nodes` 表；
- 使用独立 worker（初期可用数据库队列，后续 Celery/Dramatiq/Arq）；
- 状态机：pending/running/succeeded/failed/cancelled；
- 支持节点级日志、重试、超时、断点续跑；
- 服务启动时回收超时 running 任务。

### P1-8 文档解析能力与前端宣称不一致

当前新 KnowledgeService 仅明确支持 TXT/MD/PDF/DOCX。RAGent UI 包含 Excel/CSV 预览和复杂摄取配置，但后端未实现 Excel、CSV、HTML、URL、OCR 和表格结构保留。

整改：建立 ParserRegistry，按 MIME + 扩展名选择解析器；实现 CSV/XLSX；扫描 PDF 才进入 OCR；记录页码、sheet、行列、标题层级等结构化 metadata。

### P1-9 文件上传安全不足

需要补齐：

- 上传大小限制；
- MIME 与扩展名双重校验；
- 压缩炸弹、路径穿越和恶意 Office/PDF 防护；
- 文件哈希去重；
- 用户/知识库磁盘配额；
- 病毒扫描挂点；
- 下载接口的 Content-Disposition 与权限校验。

### P1-10 数据库没有迁移体系

当前使用 `create_all`，无法可靠升级已有数据库；表名还存在 `users_v2` 这类迁移痕迹。

整改：引入 Alembic；生成 baseline；所有 schema 变化必须有 upgrade/downgrade；CI 用空库升级和旧版本升级两种路径验证。

### P1-11 时间字段使用已弃用的 `datetime.utcnow`

测试持续产生弃用警告；数据库时间为 naive datetime，跨时区部署容易混乱。

整改：统一 UTC aware datetime，API 输出 ISO 8601 `Z`/offset；数据库和前端展示职责明确。

### P1-12 密码与 JWT 配置不完整

- JWT 默认 secret 为 `change-me-before-production`；
- 无启动时强制检查；
- 无 refresh token、撤销列表和会话管理；
- requirements 未明确固定 `argon2-cffi`；
- 没有登录限流和账号锁定。

整改：生产环境缺少强随机 JWT_SECRET 时拒绝启动；补 refresh token rotation；登录限流；安全审计日志；固定并升级密码哈希依赖。

### P1-13 RAG Trace 信息过少

当前只有节点名、状态、耗时和 JSON attributes，无法完整支持 RAGent Trace 页面期望的树结构和筛选。

需要增加：

- parentNodeId、depth、nodeType、start/end、TTFT；
- provider/model、token usage、估算费用；
- 检索 query、通道结果、融合分数、rerank 分数；
- Prompt 需脱敏且可配置是否保存；
- 分页、状态/会话/用户/时间筛选；
- Trace 保留期限和清理策略。

### P1-14 管理模型状态接口依赖内部实现细节

`management.py` 直接访问 router providers 和 breaker，耦合具体类。后续增加远程 Embedding、Rerank 或不同路由器时难扩展。

整改：定义统一 HealthSnapshot/ProviderSnapshot 契约，由容器聚合；加入最近成功时间、最近错误、P95、熔断状态和手动恢复操作。

## 四、P2：工程与性能优化

### P2-1 依赖文件已经过时

`requirements-api.txt` 注释仍写 DeepSeek + SiliconFlow 和 LangChain 0.1，但当前新 Python 核心主要直接使用 OpenAI SDK，且配置已改为 MiMo。依赖没有严格锁版本，也没有 pyproject/uv.lock 作为唯一来源。

整改：

- 使用 `pyproject.toml` + `uv.lock`；
- core、local-embedding、ocr、mysql、milvus、dev 使用 extras 分组；
- 删除新 app 未使用的 LangChain 依赖；
- 明确加入 `openai`、`python-dotenv`、`argon2-cffi`；
- CI 使用 `uv sync --frozen`。

### P2-2 前端依赖和构建体积较大

当前安装报告 20 个 npm 漏洞（1 low、9 moderate、10 high）；主 JS 约 3.47 MB，gzip 约 1.07 MB，Spreadsheet Preview 约 1.69 MB。

整改：

- 先运行 `npm audit` 分类确认可利用性，不要直接 `npm audit fix --force`；
- 管理端、图谱、Excel/PDF/DOCX 预览按路由动态加载；
- 将重型预览库拆为独立 chunk；
- 设置 bundle budget 并在 CI 阻止回退；
- 清理同时存在的 `vite.config.ts/js/d.ts` 和 tsbuildinfo 产物。

### P2-3 前端存在 `@ts-nocheck`

至少 `MarkdownRenderer.tsx` 和 `authStore.ts` 禁用了类型检查，API interceptor 也依赖 Axios 泛型技巧，容易掩盖真实契约错误。

整改：生成 OpenAPI TypeScript 类型；service 层统一 `ApiResponse<T>`；移除 `@ts-nocheck`；构建执行 `tsc --noEmit` 后再 Vite build。

### P2-4 API Response 与 HTTP 语义需要统一

有的删除接口返回 204，有的前端预期统一业务 envelope；SSE 又是另一套协议。需要形成明确规范：普通 JSON、文件下载、204、SSE 分别如何处理，避免 interceptor 误判。

### P2-5 缺少结构化日志和可观测性

目前 Trace ID 有基础实现，但缺少：JSON 日志、请求指标、模型指标、检索指标、任务指标、Prometheus/OpenTelemetry、错误聚合和敏感字段脱敏。

### P2-6 缺少限流、并发和资源保护

需要按用户/IP限制登录、聊天、上传；限制单用户并行生成数；为模型、Embedding、OCR 设置独立 semaphore；设置队列长度和过载拒绝策略。

### P2-7 缺少缓存策略

可缓存：查询改写、Embedding、文档 hash、知识库检索、推荐问题、系统配置。缓存键必须包含用户/知识库、模型版本和配置版本，防止跨租户泄漏。

### P2-8 SQLite 并发边界未明确

SQLite 适合本地单机开发。生产多 worker、高并发写入、后台任务并发时容易锁竞争。需要明确生产使用 PostgreSQL/MySQL，并测试事务隔离和连接池参数。

### P2-9 数据删除和级联不完整

模型外键未明确配置数据库级 `ON DELETE CASCADE`。删除用户、知识库、文档、会话时可能残留 Chunk、Trace、文件或向量。

整改：数据库级约束 + service 级外部资源清理；失败时使用 outbox/补偿任务；增加孤儿资源巡检命令。

### P2-10 检索质量缺少评测闭环

目前只有单元测试，没有标准问答集、Recall@K、MRR、nDCG、引用正确率、拒答准确率和端到端答案评估。

整改：建立离线评测数据集；每次调整 chunk、embedding、fusion、rerank、prompt 后自动对比基线。

## 五、测试覆盖缺口

当前 8 个测试通过，但主要是模块和 ASGI 基础流程。必须增加：

1. 前端 service 与 OpenAPI 契约测试；
2. Playwright 浏览器 E2E：登录、对话、停止、会话切换、知识库上传、后台主要页面；
3. MiMo 流式协议测试：content、错误、超时、限流、断连；真实 API 测试应单独标记，不进入普通 CI；
4. 多租户越权测试；
5. 文件安全与格式矩阵测试；
6. 数据库迁移测试；
7. Milvus 集成测试和服务重启后的索引一致性测试；
8. 后台任务崩溃恢复测试；
9. 并发聊天和上传压力测试；
10. 前端 TypeScript、ESLint、npm audit、bundle budget。

## 六、推荐执行顺序

### 阶段 A：让现有 UI 名副其实

1. 自动生成前端接口清单和契约测试；
2. 完成 Auth/User/Admin 权限闭环和初始化管理员 CLI；
3. 完成知识库、文档、Chunk 的 RAGent Compatibility API；
4. 完成 Trace Compatibility API；
5. 完成停止生成、反馈、推荐问题；
6. 对未实现后台模块统一返回 501，不再出现未知 404。

阶段 A 验收：RAGent 原版 UI 中所有菜单都能打开；已实现功能可真实操作；未实现功能有明确提示。

### 阶段 B：保证 RAG 核心可靠

1. 持久化 ChatTaskRegistry 和取消机制；
2. 多轮历史与 token budget；
3. Embedding API + 小模型 + 向量索引版本；
4. 持久化摄取任务；
5. 文件安全与解析格式扩展；
6. 完整 Trace 和离线评测。

### 阶段 C：达到可部署标准

1. Alembic；
2. PostgreSQL/MySQL 生产配置；
3. uv 锁依赖；
4. 日志、指标、告警；
5. 限流与配额；
6. Docker Compose、反向代理、健康检查、备份恢复；
7. 前端依赖安全和代码分包。

## 七、交给执行 AI 的总提示词

```text
你正在维护 D:\Project\rag-project。

目标：把当前“RAGent 原版前端 + Python FastAPI 骨架”补成真正可用的 Python 版 RAGent。

硬性约束：
1. UI 必须沿用 D:\Project\ragent\frontend 的原始设计，不自行重画、不删菜单来掩盖后端缺失。
2. 后端仅使用 Python，当前阶段不使用 Java/Go。
3. 使用 uv 管理 Python 环境。
4. 不允许用静态假数据冒充已实现功能。
5. 保持用户、会话、知识库、文档、Trace 的租户隔离；所有管理接口必须校验 admin。
6. 每完成一个接口，同时补单元测试、契约测试；关键流程补 Playwright E2E。
7. 不输出、提交或记录任何 API Key。
8. 先阅读 docs/implementation-gap-audit.md，并严格按其中阶段 A、B、C 执行。

首先执行阶段 A。开始前自动对比 web/src/services/*.ts 与 FastAPI OpenAPI，生成缺失接口列表；之后逐项实现并持续运行：
- uv run python -m pytest -q
- npm run build
- TypeScript/ESLint 检查

不要只汇报计划；直接实现、验证，并在每轮结束列出已完成接口、剩余接口和测试结果。
```

## 八、完成定义

只有同时满足以下条件，才能称为“Python 版 RAGent 已完成”：

- 原版前端所有菜单对应真实 Python API；
- 核心功能不存在未知 404 或静态假数据；
- 权限、租户隔离、任务恢复和数据迁移有自动化测试；
- 对话支持正常完成、错误结束、主动停止和断线取消；
- 文档从上传到索引可追踪、可重试、可恢复；
- 向量索引在服务重启后仍可用且模型版本一致；
- 前后端契约、E2E、依赖安全和部署检查进入 CI；
- README 与实际行为一致。
