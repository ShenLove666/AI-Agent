# Python 架构重构说明

本项目不复制 ragent 的 Java 代码，而是复刻其模块边界和工程能力。第一阶段全部使用 Python，后续如果需要迁移 Go，各模块可通过当前接口边界逐个替换。

## 模块映射

| ragent | Python 实现 | 职责 |
|---|---|---|
| `framework` | `app/framework` | 配置、统一错误、HTTP 约定、Trace、SSE、认证上下文 |
| `infra-ai` | `app/infra_ai` | Chat、Embedding、Rerank、Vision 客户端，路由、熔断和降级 |
| `bootstrap` | `app/modules` + `app/api` | RAG、检索、知识库、入库、会话、用户和 HTTP API |
| `mcp-server` | 后续 `services/mcp_server` | 独立 MCP 工具进程，不与主 API 耦合 |

## 依赖方向

```text
app/api  -> app/modules -> app/infra_ai
   |            |              |
   +------------+--------------+
                v
          app/framework
```

业务模块只依赖 AI 接口，不依赖 DeepSeek、OpenAI、Milvus 等具体实现。供应商和数据库切换通过装配层完成。

## RAG 检索漏斗

1. 查询理解与改写
2. 向量、关键词、图谱、联网通道并行检索
3. 单通道超时与故障隔离
4. 去重与加权 RRF 融合
5. Rerank
6. 元数据与引用富化
7. 上下文预算裁剪
8. Prompt 构建与流式生成

候选召回数、Rerank 数量和最终上下文数量必须分开配置，不能继续共用一个 `TOP_K`。

## 入库 Pipeline

默认节点顺序为：

```text
Fetcher -> Parser -> Chunker -> Enhancer -> Enricher -> Indexer
```

每个节点可条件跳过，输出自动传递给后续节点，并记录任务级、节点级状态、耗时和错误。后续可把任务执行从进程内队列替换为 Redis Streams、RabbitMQ 或 Kafka，而不改变节点实现。

## 迁移原则

- 不继续扩展旧 `server.py`；所有新接口进入 `app/api`。
- 不在业务服务里直接初始化模型客户端或向量库。
- 不将 LangChain 对象作为领域模型传递。
- 外部资源都通过 `Protocol` 接口和装配层注入。
- Python 版本稳定后再评估 Go；优先迁移无模型推理的高并发模块。
