# Production RAG 可靠性改造

本轮改造聚焦“检索是否真的融合、索引是否一致、流式调用是否可控、请求是否可安全重试”，而不是继续增加未闭环的功能入口。

## 1. Hybrid Retrieval 身份统一

关键词通道与向量通道统一使用数据库 `KnowledgeChunk.id`：

```text
SQLite chunk.id = 501
keyword metadata.chunk_id = 501
vector record.id = "501"
vector metadata.chunk_id = 501
```

Weighted RRF 因而能把同一 Chunk 的多通道贡献累加，并在 `channel_attribution` 中保留来源、原始排名和分数。回归测试验证相同 Chunk 最终只占一个上下文位置。

## 2. 重建索引清理

文档重新切块后，系统先按 `document_id` 删除上一代向量，再写入使用真实数据库 Chunk ID 的新记录。即使新版本块数减少，也不会留下可被召回的旧尾部 Chunk。

当前策略优先保证“不召回已删除内容”。如果向量写入失败，文档会标记为 `failed`，不会伪装成索引成功。后续可进一步升级为双版本索引和原子切换。

## 3. 可控的流式生成

模型路由支持三个超时边界：

- `CHAT_FIRST_TOKEN_TIMEOUT_SECONDS`：连接后等待首 Token 的最长时间；
- `CHAT_IDLE_TIMEOUT_SECONDS`：相邻 Token 之间允许的最长空闲时间；
- `CHAT_TIMEOUT_SECONDS`：单个供应商总生成上限。

手动停止会同时等待“下一个 Token”和取消事件。取消先发生时，系统会立即取消上游 `anext()`，无需等待卡住的模型继续输出。Trace 的 generation 节点记录 `ttft_ms`、回答字符数和 interrupted 状态。

## 4. 请求幂等

每轮前端请求生成 UUID `requestId`，后端通过 `chat_request_runs` 表持久化：

```text
processing -> completed
           -> failed -> processing（允许重试）
           -> cancelled -> processing（显式重试）
```

- `processing`：拒绝相同请求并发执行；
- `completed`：直接回放已落库回答，不再次调用模型；
- `cancelled`：保留部分回答但不进入成功缓存；
- `failed`：保留原用户消息并允许重新执行；
- 自动盲重试关闭，避免网络抖动启动第二个生成任务。

该记录以 `(user_id, request_id)` 唯一约束隔离不同用户，避免跨用户碰撞和结果泄漏。

请求同时保存 SHA-256 指纹，覆盖 conversation、question、deep thinking、RAG 开关和知识库范围。同一 requestId 只有指纹一致时才允许回放或重试，否则返回 409，避免把旧问题答案返回给新问题。

## 验证覆盖

- 相同数据库 Chunk 的 keyword/vector 命中融合为一个结果；
- 向量记录使用真实 Chunk ID；
- 文档重新入库两次均先删除旧向量；
- 卡死模型触发首 Token 超时；
- 停止事件可中断卡死模型；
- 相同 `request_id` 第二次请求回放原结果，模型只调用一次。
