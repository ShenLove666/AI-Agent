# 邻里鲜选 AI 运营台 — 搭建部署与实现原理手册

> 适用读者：开发 / 运维 / 需要从零搭建与理解系统实现的人员
> 目标环境：Windows 本地开发 + Linux 服务器部署（SQLite 单机架构）

---

## 目录

1. [系统架构总览](#1-系统架构总览)
2. [技术栈](#2-技术栈)
3. [目录结构](#3-目录结构)
4. [本地环境准备](#4-本地环境准备)
5. [配置详解（.env）](#5-配置详解)
6. [数据库与迁移](#6-数据库与迁移)
7. [演示数据与零售数据导入](#7-演示数据与零售数据导入)
8. [启动服务](#8-启动服务)
9. [测试与质量门禁](#9-测试与质量门禁)
10. [服务器部署](#10-服务器部署)
11. [全流程实现原理](#11-全流程实现原理)
12. [故障排查](#12-故障排查)

---

## 1. 系统架构总览

```
┌────────────────────────────────────────────────────────────┐
│  前端 Web（React 18 + Vite + Tailwind + zustand）            │
│  web/  →  npm run dev / build → dist/                       │
└──────────────┬─────────────────────────────────────────────┘
               │  /api/v1/*（同源代理，dev 代理到 8081）
┌──────────────▼─────────────────────────────────────────────┐
│  后端 API（FastAPI + SQLAlchemy 2.0 + Alembic）             │
│  server.py → uvicorn :8081                                 │
│                                                            │
│  app/api/       路由层（权限依赖注入点）                      │
│  app/modules/   业务域（users/support/commerce/knowledge/   │
│                 evaluation/settings/demo/...）              │
│  app/framework/ 基础设施（config/database/errors/migrations/ │
│                 response/trace）                            │
│  migrations/    Alembic 版本（0001 → 0016）                 │
└──────┬──────────────────────────────┬──────────────────────┘
       │                              │
       ▼                              ▼
┌─────────────┐            ┌──────────────────────┐
│ SQLite      │            │ 模型服务（OpenAI 兼容）│
│ data/*.db   │            │ DashScope / DeepSeek  │
│ （单文件）    │            │ 向量后端可关（disabled）│
└─────────────┘            └──────────────────────┘
```

**设计要点**

- **单机单体架构**：FastAPI 进程内完成路由 → 权限校验 → 业务服务 → SQLite 持久化，无需消息队列/独立 worker
- **权限三层模型**：角色（role）→ 权限（permission）→ API 依赖。前端菜单只是展示层，真正的权限在**每个 API 端点的 FastAPI 依赖**上强制校验
- **数据隔离**：组织成员关系（organization_members）决定数据可见范围；跨组织资源统一 404（不暴露存在性）
- **事件溯源式审计**：业务操作（升级、决议、质检标注、设置修改）落 support_events / 审计表，指标由真实事件聚合而非编造

## 2. 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端 | Python 3.12 + FastAPI | 异步 ASGI；`app.main:app` |
| ORM | SQLAlchemy 2.0（Mapped/Declarative） | 同步 Session + sessionmaker |
| 迁移 | Alembic | `migrations/versions/0001~0016` |
| 数据库 | SQLite（默认 `data/ragent-v4-flash.db`） | 可通过 `DB_URL` 切换；生产多实例请使用外部数据库 |
| 认证 | JWT（python-jose, HS256）+ argon2 密码哈希 | 代码兼容默认 43200 分钟（30 天）；生产应显式设为 720 分钟（12 小时）或更短 |
| 前端 | React 18 + TypeScript + Vite | 路由 react-router v6，状态 zustand |
| 样式 | Tailwind CSS（自定义 tokens）+ shadcn 风格组件 | `globals.css` 定义设计系统 |
| 模型 | OpenAI 兼容 Chat Completions（urllib/openai） | DashScope / DeepSeek / 备用端点按优先级 failover |
| 向量检索 | 可选 milvus-lite / disabled | **服务器建议 disabled**（见 §10 坑位） |

## 3. 目录结构

```
rag-project/
├── server.py                 # 启动入口（uvicorn :8081）
├── app/
│   ├── main.py               # FastAPI app 组装
│   ├── application_core.py   # 容器组装（database/retrieval/chat/services）
│   ├── api/                  # 路由 + 权限依赖
│   │   ├── dependencies.py   # make_permission_requirement / CurrentUser 等
│   │   ├── support.py        # 工单/回复/升级/质检（31+ 端点）
│   │   ├── retail.py         # 关联规则/方案/任务（18 端点）
│   │   ├── knowledge*.py     # 知识库 CRUD/文档/分块（60+ 端点）
│   │   ├── auth.py settings.py dashboard.py users...
│   ├── modules/
│   │   ├── users/            # 用户/角色/权限（permissions.py 4 角色模型）
│   │   ├── support/          # 工单状态机、升级生命周期、质检
│   │   ├── commerce/         # 购物篮→关联规则→方案→任务→复测回填
│   │   ├── knowledge/        # 知识库/文档/分块/发布版本
│   │   ├── evaluation/       # 评测运行
│   │   ├── settings/         # 运行时设置（版本 CAS + 审计）
│   │   ├── demo/             # 确定性演示数据 seed / clear
│   │   ├── rag/ retrieval/ vector/ chat/ ...
│   ├── framework/            # config/database/migrations/errors/response/trace
├── migrations/versions/      # 0001_current_schema → 0016_optimization_verification_runs
├── scripts/
│   ├── deploy.sh             # 服务器同步 + 重启 + 健康检查
│   ├── manual/               # 手工验证脚本（不纳入 pytest）
├── tests/                    # pytest 套件（当前 252 收集，含 RBAC 矩阵）
├── web/                      # 前端（src/pages/admin/* 后台页面）
├── data/                     # SQLite 数据文件（git 忽略）
└── docs/                     # 本手册
```

## 4. 本地环境准备

### 4.1 依赖

| 组件 | 版本要求 | 获取 |
|---|---|---|
| Python | ≥ 3.11（开发用 3.12） | python.org |
| Node.js | ≥ 18 | nodejs.org |
| Git | 任意 | git-scm.com |

### 4.2 后端虚拟环境

```bash
# Windows（PowerShell / Git Bash）
cd rag-project
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Linux: .venv/bin/pip

# 若项目附带 requirements 且已安装，验证：
.venv/Scripts/python -c "import fastapi, sqlalchemy, alembic; print('ok')"
```

`requirements-dev.txt` 包含 Alembic 与测试工具；仅运行 API 时可使用
`requirements-api.txt`。依赖文件目前不是完整的锁文件，生产发布应在构建阶段固定并审计实际版本，不能把开发机的 `.venv` 当作依赖清单。

### 4.3 前端依赖

```bash
cd web
npm install
```

## 5. 配置详解

项目读取根目录 `.env`（`app/framework/config.py` 中 **override=True**，覆盖系统环境变量——系统残留旧变量会导致模型 401）。可复制仓库根目录的 `.env.example` 作为模板；它不含密钥。生产应由 systemd/Supervisor、容器编排或密钥管理系统注入私密变量，不要把真实 `.env` 放进版本库。关键变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DB_URL` | `sqlite:///./data/ragent-v4-flash.db` | 数据库连接串 |
| `CORS_ORIGINS` | `http://localhost:3000`（代码兼容默认） | Vite 本地开发通常使用 5173，需显式配置；生产只允许实际 HTTPS 来源 |
| `JWT_SECRET` | 内置占位值（不安全） | **生产必须注入至少 32 字节随机值，并定期轮换**；不要使用仓库模板中的占位符 |
| `JWT_EXPIRE_MINUTES` | `43200`（30 天，代码兼容默认） | 生产建议显式设为 `720`（12 小时）或更短 |
| `VECTOR_BACKEND` | `milvus` | 向量后端；**无 milvus 环境必须 `disabled`**（见 §12） |
| `DASHSCOPE_API_KEY` | — | 百炼模型密钥（识图/chat 通用） |
| `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 百炼 OpenAI 兼容端点 |
| `VISION_MODEL` | `qwen3.7-plus` | 识图 / chat 默认模型 |
| `DEEPSEEK_API_KEY` | — | DeepSeek 备用端点 |
| `BACKUP_LLM_API_KEY` / `_BASE_URL` / `_MODEL` | — | 第三备用端点（failover 优先级 5→10→20） |
| `UPLOAD_DIR` | — | 文档上传目录 |

> 模型端点按优先级 failover：mimo(5) → deepseek(10) → backup(20)，配置了 key 即启用。

## 6. 数据库与迁移

### 6.1 首次启动自动迁移

启动服务时 `upgrade_database(container.database)` 自动执行 Alembic 迁移到最新版本（当前 head：`0016_optimization_verification_runs`），无需手动操作。生产发布前仍应先做一致性备份并在副本数据库上演练迁移；自动迁移失败会阻止服务启动，不提供自动回滚。

### 6.2 手动执行

```bash
.venv/Scripts/python -m alembic upgrade head          # 升级到最新
.venv/Scripts/python -m alembic revision --autogenerate -m "描述"  # 生成新迁移
```

### 6.3 迁移历史（0001 → 0016）

| 版本 | 内容 |
|---|---|
| 0001_current_schema | 初始全量表结构 |
| 0002 / 0003 / 0004 | demo 来源元数据、评测数据集、索引元数据 |
| 2fce55de2167 | 即时零售运营（关联规则/方案/任务） |
| 0005 | 客服质量闭环（质检标注/知识缺口） |
| 0006 | 零售数据溯源（observed/synthetic 标注） |
| 0007 | V3 订单上下文与对外发送 |
| 0008 | 升级生命周期（支持升级单状态机） |
| 0009 | 运行时设置 + 组织成员 + 方案状态机 + 任务回填 |
| 0010 | Agent 执行摘要 |
| 0011 | 知识文档来源类型 |
| 0012 | 修复知识归属并回填来源类型 |
| 0013 | Trace 请求 ID |
| 0014 | Trace 节点起始偏移 |
| 0015 | Trace 首 Token 延迟（TTFT） |
| 0016 | **经营效果复测表与优化任务显式外键**（当前 head） |

## 7. 演示数据与零售数据导入

### 7.1 管理员账号

```bash
# 创建管理员（或 --username 指定）
.venv/Scripts/python -m app.cli create-admin --username admin --password '你的密码'
# 已有用户提升为管理员
.venv/Scripts/python -m app.cli promote-admin --username someuser
```

### 7.2 完整演示数据（含客服工单 / 升级 / 质检）

```bash
# 密码至少 10 位；-r 表示先清理旧演示数据
DEMO_SEED_PASSWORD='DemoPass@2026' .venv/Scripts/python -m app.cli seed-demo
# 清理演示数据
.venv/Scripts/python -m app.cli clear-demo --yes
```

seed 会创建：演示商家组织（`邻里鲜选演示商家`）+ 账号（merchant-demo/support-admin/demo-supervisor/demo-operator/demo-agent）+ 360 条工单 + 质检标注 + 零售快照。

### 7.3 零售购物篮数据导入

```bash
.venv/Scripts/python -m app.cli seed-retail --source-dir ./data/baskets --owner demo-admin
```

`--source-dir` 需包含两个 CSV（UTF-8 with BOM 亦可）：

**GoodsTypes.csv**（商品分类）：

```csv
Goods,Types
牛肉,肉类
根茎类蔬菜,果蔬
全脂牛奶,乳制品
香草,调味品
```

**GoodsOrder.csv**（购物篮明细，`id` 为购物篮编号，同一 id 的多行构成一个篮子）：

```csv
id,Goods
1,牛肉
1,根茎类蔬菜
2,牛肉
2,根茎类蔬菜
...
```

导入后自动计算关联规则，并**自动为 top 规则预生成种子运营方案**（防重复校验会拦截同规则再次创建）。

## 8. 启动服务

### 8.1 后端

```bash
# Windows
VECTOR_BACKEND=disabled .venv/Scripts/python server.py
# Linux / 服务器
VECTOR_BACKEND=disabled .venv/bin/python -u server.py > logs/server.log 2>&1 &
```

- 开发可监听 `0.0.0.0:8081`；生产建议仅监听 `127.0.0.1:8081` 并由反向代理对外提供 HTTPS。健康检查：`GET /api/v1/health` → `{"success":true,...,"status":"up"}`
- 首次启动自动建表/迁移

### 8.2 前端

```bash
cd web
npm run dev        # 开发：http://127.0.0.1:5173（/api 代理到 8081）
npm run build      # 生产构建 → dist/
```

生产模式下后端直接托管 `web/dist` 静态文件。

## 9. 测试与质量门禁

```bash
# 后端全量测试（当前 252 收集：250 passed，2 个环境相关 skip）
.venv/Scripts/python -m pytest tests/ -q

# 重点测试文件
tests/test_rbac_matrix.py        # 完整越权矩阵：11 个 API × 4 角色 + 跨组织 404
tests/test_support_escalation.py # 升级生命周期状态机
tests/test_reply_review.py       # AI 回复审核闭环
tests/test_migrations.py         # 迁移一致性

# 前端
cd web
npm run typecheck                 # TypeScript 类型（app + node 配置）
npx eslint src --max-warnings=0  # Lint
npm test                         # vitest（当前 303 用例）
npm run build                    # 构建门禁
```

仓库还提供 `.github/workflows/ci.yml`：每次 push/PR 在干净的 Python 3.12 + Node 20 环境执行编译、后端测试、API 契约、前端测试、类型检查、Lint 与生产构建。

## 10. 服务器部署

### 10.1 一次性准备（服务器）

```bash
mkdir -p /home/sj/rag-project-<version>
# 软链接复用依赖（升级版本时避免重装）：
ln -s /home/sj/rag-project-<old-version>/.venv /home/sj/rag-project-<version>/.venv
# 准备仅服务账号可读的 .env（含 APP_ENV=production、VECTOR_BACKEND=disabled、
# 随机 JWT_SECRET、JWT_EXPIRE_MINUTES=720 与模型密钥）
# 准备 data/、uploads/、backups/ 和 logs/ 的持久化目录与权限
```

生产入口建议使用 systemd/Supervisor 托管进程，并让 Uvicorn 只监听
`127.0.0.1:8081`；由 Nginx/Caddy 在 `443` 终止 TLS 后反代到该端口。防火墙应拒绝公网访问
8081，应用的 `/docs`、`/redoc`、`/openapi.json` 也应按环境限制或关闭。不要把演示账号
（默认密码 `AdminDemo@2026`）带到公网。

### 10.2 部署脚本（本地执行）

```bash
bash scripts/deploy.sh [目标目录]   # 默认 rag-project-20260809-runtime-settings-v5
```

`deploy.sh` 流程（**演示/单机预览辅助脚本，不是生产发布控制器**）：

```
1. tar 打包（排除 .git/.venv/node_modules/data/*.db/.env/logs 等）
2. ssh 同步解包到 /home/sj/<target>
3. 按 8081 端口找到旧 PID → kill
4. nohup 后台启动 .venv/bin/python -u server.py
5. curl 健康检查 /api/v1/health 验证
```

脚本不会自动安装依赖、备份数据库、执行回滚、验证迁移结果、配置 TLS、轮转日志或在进程崩溃后自动拉起；它还会按 8081 端口查找并终止进程，不能在共享主机上盲目执行。生产切换至少应先完成：

1. 对 SQLite 数据库做一致性备份并记录校验和，保留最近多份且至少一份异机/对象存储副本；
2. 在副本上运行 `alembic upgrade head` 并验证应用健康、登录和关键闭环；
3. 由 systemd/Supervisor 启动新版本，等待就绪后再切换反代；
4. 保留上一版本目录和明确的回滚命令，迁移不可逆时先确认恢复方案；
5. 配置日志轮转、磁盘空间/进程/数据库备份告警和定期恢复演练。

### 10.3 部署要点（踩坑记录）

| 坑 | 现象 | 规避 |
|---|---|---|
| `.env` 被本地覆盖 | 服务器 VECTOR_BACKEND 丢失 → 默认 milvus → 首次向量搜索触发 **libarrow segfault** → "网络错误" | deploy.sh 已 exclude `.env`；服务器 .env 保持 `VECTOR_BACKEND=disabled` |
| 依赖重复安装 | 部署慢、版本漂移 | 新目录软链接旧 .venv |
| 端口冲突 | 服务起不来 | 按端口 PID 精确 kill，不按进程名 |
| 日志缓冲 | 启动"看起来卡住" | 等待 10s 再健康检查；日志在 logs/server.log |

> 安全底线：曾经出现在本地 `.env` 或日志中的 API key 一律视为已泄露，必须立即在供应商控制台撤销并重新注入；仅依赖 `.gitignore` 不能撤销已复制到服务器、备份或聊天记录中的密钥。

## 11. 全流程实现原理

### 11.1 一条客服工单的完整生命周期

```
顾客提问 ──► POST /support/cases 创建工单（status=pending）
                 │
                 ▼
        客服选中工单（GET /support/cases/{id} + /workspace 加载订单上下文）
                 │
                 ▼
        点击「生成」──► POST /support/cases/{id}/suggestions
                 │         ├─ 检索已发布知识（retrieval，按用户/组织隔离）
                 │         ├─ 组装 Prompt（含知识 + 订单上下文）
                 │         ├─ 调用模型端点（mimo→deepseek→backup failover）
                 │         └─ 输出：回复草稿 + intent/risk/missingFacts + 引用证据
                 │
                 ▼
        人工审核：
          ├─ 采纳/修订 ──► POST decide（accepted/edited + 最终文本）
          │                    └─ 记录 support_events（采纳率指标来源）
          └─ 升级主管 ──► POST /cases/{id}/escalations
                               ├─ 校验分类/风险等级/同 case 唯一进行中升级
                               ├─ 工单 → escalated
                               └─ 附带 aiDiagnosis（intent/risk/missingFacts）
                 │
                 ▼
        主管队列（GET /escalations）：
          ├─ 接管 accept（pending → accepted）
          ├─ 决议 resolve（approved_refund / approved_compensation / ...）
          ├─ 要求证据 / 转专员 / 退回 return
          └─ 决议写回工单（resolve_gap 同步知识缺口）
                 │
                 ▼
        解决工单（transition resolved + resolutionCode/Note）
                 │
                 ▼
        质检闭环：质量与缺口页聚合 → 缺口回填知识改进任务 → 新知识版本发布
```

**关键实现**：
- 状态机约束在 service 层（`SupportService`），API 只做参数校验与权限
- 指标（解决率/采纳率/引用覆盖）由 `support_events` **事件聚合**计算，不调用模型编造
- 升级单创建有**幂等/防重复**（同 case 仅一个 pending/accepted 升级）

### 11.2 一条运营方案的完整生命周期

```
购物篮 CSV ──► seed-retail / import_baskets
                 │   └─ Apriori 风格关联规则（lift/confidence/support/count）
                 ▼
        规则列表（GET /retail/overview）
                 │
                 ▼
        创建方案（POST /retail/campaigns）→ status=draft
                 │   └─ 防重复：同规则存在 draft/confirmed 时 400
                 ▼
        确认方案（transition confirm, expectedVersion=1 乐观锁）
                 │   └─ 生成 CampaignVersion v1（规则快照）
                 ▼
        发布方案（transition publish，仅 admin）→ status=published
                 │   └─ 自动创建优化任务（OptimizationTask）
                 ▼
        任务执行：assign（指派）→ verify（复测同规则）→ advance（完成）
                 │   └─ 复测结果回填方案
                 ▼
        已完成（completed）
```

**关键实现**：
- 方案/任务共用 `lock_version` 做**乐观锁 CAS**：transition 必须带 expectedVersion，版本不符返回 409
- 种子数据会预占 top 规则（published 释放 / draft 占用），测试与演示数据均需避开占用规则
- 复测（verify）对同一规则重新评估，评价指标变化后回填，形成"验证结果闭环"

### 11.3 RBAC 权限实现（三层模型）

```
用户（users_v2.role）             角色 → 权限映射（ROLE_PERMISSIONS）
   │  user / supervisor /           users/permissions.py 中 20 项权限
   │  operator / admin              ALL_PERMISSIONS 全集
   ▼                                VALID_ROLES = frozenset(keys)
permissions_for(db, user)
   ▼
FastAPI 依赖：make_permission_requirement("support.case.read")
   ▼
每个端点：@router.post("/cases/{id}/escalations",
        dependencies=[Depends(make_permission_requirement("support.case.escalate"))])
   ▼ 无权限 → 403 AppError

数据范围（另一维度）：
resolve_owner(db, user) → 组织 owner_user_id（无成员时回退 user.id）
跨组织访问 → require_* 查不到 → 404（不暴露资源存在性）
```

- 前端菜单过滤（roles + permission 双重）**只是展示层**；后端 API 硬校验是真正的安全边界
- `tests/test_rbac_matrix.py` 用 4 角色 × 11 个代表性 API 全矩阵验证，含跨组织 404

### 11.4 运行时设置（版本 CAS + 审计）

```
PATCH /rag/settings
  body: { expectedVersion, changes: [{key,value}], resetKeys }
    ├─ 白名单校验（15 项，未知 key 拒绝）
    ├─ expectedVersion 与 config_meta 当前版本比对 → 不匹配 409
    ├─ 写入 runtime_settings + 版本 +1
    ├─ 记录 RuntimeSettingAudit（谁/何时/改了什么）
    └─ restart 作用域变量 → lifespan 重建容器时 apply_restart_env_overrides
```

### 11.5 演示数据（确定性 seed）

- `DemoSeedService`：**确定性**生成（固定种子），支持幂等 upsert 与安全 clear
- 组织-成员关系替代旧的"管理员自动代理"魔法：demo-* 账号只有作为成员才能看到商家数据
- `demo/support` 数据带 `is_demo` 标记，界面展示"演示数据 · 指标由工单事件计算"诚实标注

### 11.6 识图能力（无多模态模型的兜底）

`~/.agents/skills/vision-bridge/vision_bridge.py`：当前模型不支持图片时，用多模态视觉模型（默认 **Qwen3.7-Plus**，DashScope OpenAI 兼容端点）读图。配置：`.env` 的 `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` / `VISION_MODEL=qwen3.7-plus`；脚本默认值与之一致，模型/端点/密钥均可用环境变量切换，不绑定厂商。

## 12. 故障排查

| 症状 | 排查步骤 |
|---|---|
| 启动后首次检索崩溃（SIGSEGV / libarrow） | `.env` 缺 `VECTOR_BACKEND=disabled`；确认服务器 .env 未被部署覆盖 |
| 模型调用 401 | 系统环境变量残留旧 key 覆盖 .env → 清环境变量或确认 .env override 生效 |
| 模型调用报 Arrearage | 百炼账号欠费/免费额度未生效，控制台充值后重试 |
| 登录 401 但账号存在 | 密码被重置过？用 `create-admin`/`promote-admin` 重建或重置 hash |
| 页面 403 | 角色权限不足（预期）；换 admin 验证 |
| 工单/方案看不到 | 组织成员关系缺失 → seed-demo 重建或手工绑定 organization_members |
| 前端构建报 chunk 过大 | 仅警告，可忽略或按需 code-split |
| 部署后旧页面 | 浏览器强刷（Ctrl+Shift+R）；确认 dist 时间戳已更新 |

---

*文档维护：每次功能迭代后同步更新 §11 实现原理与 §3 目录结构。*
