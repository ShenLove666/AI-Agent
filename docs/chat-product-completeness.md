# 对话产品闭环改造

本轮改造把前端已有但未完整接入后端的交互补成可演示、可持久化、可回归验证的产品闭环。

## 深度思考

- 前端 `deepThinking` 参数贯穿 SSE 接口、RAG 服务、模型路由和供应商适配器；
- DeepSeek 在开启时切换到 `deepseek-reasoner`，MiMo 使用兼容接口的 thinking 开关；
- reasoning 与最终回答使用不同流事件，界面可以分别展示；
- 思考内容与耗时随助手消息落库，刷新历史会话后仍可恢复；
- Trace 记录请求模式、是否启用推理及思考字符数，便于质量分析。

## 历史会话恢复

消息历史接口不再只返回正文，而是恢复完整界面状态：

- 引用与来源；
- 点赞/点踩状态；
- 正常、生成中、已停止和失败状态；
- 思考内容与耗时；
- 推荐追问。

## 推荐追问

推荐问题接口统一返回 `SUCCESS`、`EMPTY` 或 `FAILED` 状态，并把生成结果写回对应助手消息。再次打开会话时无需重新请求模型即可恢复推荐问题。

## 会话重命名

会话重命名已由前端本地假更新改为 `PATCH /api/v1/conversations/{id}`，服务端校验会话所有权并持久化标题。

## 管理端入口收敛

侧边栏只展示已形成后端闭环的仪表盘、运营洞察、知识库、运行追踪、用户和系统设置。尚未完成的 Agent、知识图谱、意图、摄取配置、映射、审计与示例问题入口暂时隐藏，代码和直达路由仍保留，便于后续逐项启用。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app tests

Set-Location web
npx eslint src/stores/authStore.ts src/services/sessionService.ts src/stores/chatStore.ts src/pages/admin/AdminLayout.tsx --max-warnings 0
npm run build
```

重点回归覆盖深度思考模型选择与 SSE 落库、历史消息 DTO、推荐问题持久化和真实会话重命名。
