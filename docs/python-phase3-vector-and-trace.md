# 第三阶段：向量检索、改写与 Trace

## 可选环境变量

```bash
# 配置后启用本地向量检索；未配置时仅启用关键词通道
EMBED_MODEL_PATH=/path/to/bge-small-zh-v1.5
EMBED_DEVICE=cuda
EMBED_DIMENSION=512

# memory 仅用于开发；生产建议 milvus
VECTOR_BACKEND=milvus
MILVUS_URI=http://127.0.0.1:19530
MILVUS_COLLECTION=ragent_chunks_v2

# 配置后启用 CrossEncoder Rerank
RERANK_MODEL_PATH=/path/to/bge-reranker-base
RERANK_DEVICE=cuda
RERANK_CANDIDATE_LIMIT=20
```

## 启用后的检索链路

```text
原问题
  -> 查询改写（失败自动回退原问题）
  -> 关键词与向量通道并行执行
  -> 单通道超时/故障隔离
  -> 加权 RRF
  -> 可选 CrossEncoder Rerank
  -> 来源与排名富化
  -> 上下文裁剪
  -> LLM 生成
```

## Trace

每次问答写入 `rag_trace_runs`，各阶段写入 `rag_trace_nodes`。当前记录：

- `rewrite`：改写结果与是否回退
- `retrieval`：通道结果数、错误及耗时
- `prompt`：上下文条数与字符数
- `generation`：答案长度、耗时及错误

Trace 数据已持久化，管理端查询 API 和可视化将在后续阶段补充。

## VectorStore

领域层只依赖 `VectorStore` Protocol。目前提供：

- `InMemoryVectorStore`：测试和开发使用，重启后数据丢失
- `MilvusVectorStore`：生产适配器，支持远程 Milvus 和 Milvus Lite

后续增加 pgvector 时无需修改检索引擎、入库服务或聊天编排。
