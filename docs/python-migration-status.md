# Python 重构进度

## 已完成

- FastAPI 应用工厂与模块化单体入口
- 统一异常、响应格式、Trace ID 与请求耗时
- Chat / Embedding / Rerank 抽象接口
- OpenAI 兼容 Chat Provider
- 模型优先级路由、超时、三态熔断与故障降级
- 并行检索引擎、单通道故障隔离、加权 RRF、去重、Rerank 接口
- 节点化文档入库 Pipeline
- JWT 注册登录与用户隔离
- 会话、消息和引用持久化
- 知识库、文档、Chunk 数据模型
- TXT、Markdown、PDF、DOCX 解析
- 文本分块与后台入库
- jieba 中文关键词检索
- 同步聊天和 SSE 流式聊天 API

## 当前新版 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/architecture` | 架构能力查看 |
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/login` | 登录 |
| POST/GET | `/api/v1/conversations` | 创建/查询会话 |
| GET | `/api/v1/conversations/{id}/messages` | 查询消息 |
| DELETE | `/api/v1/conversations/{id}` | 删除会话 |
| POST/GET | `/api/v1/knowledge-bases` | 创建/查询知识库 |
| POST/GET | `/api/v1/knowledge-bases/{id}/documents` | 上传/查询文档 |
| POST | `/api/v1/chat` | 同步 RAG 问答 |
| POST | `/api/v1/chat/stream` | SSE 流式 RAG 问答 |

## 下一阶段

1. 实现本地 Embedding Provider 和 Milvus / pgvector Vector Channel。
2. 增加 Elasticsearch/OpenSearch BM25 通道，替换当前 SQLite LIKE 检索。
3. 接入 Rerank Provider，并校验候选漏斗配置。
4. 增加查询改写、意图树、Prompt 配置和会话摘要。
5. 增加持久化 RAG Trace、审计和反馈。
6. 迁移前端到 `/api/v1` 契约。
7. 将进程内后台任务替换为可靠任务队列。
