# DeepSeek V4 Flash 默认模型升级设计

## 目标

将项目的 DeepSeek 默认模型从已弃用的 `deepseek-chat` / `deepseek-reasoner`
升级为官方正式模型 `deepseek-v4-flash`。普通对话与深度思考均使用同一正式模型，
同时保留 `DEEPSEEK_MODEL` 和 `DEEPSEEK_REASONING_MODEL` 的环境变量覆盖能力。

## 范围

- 更新 `app/framework/config.py` 中 DeepSeek 端点的两个默认模型名。
- 增加配置层回归测试，验证未设置模型环境变量时两个模型均为
  `deepseek-v4-flash`，显式环境变量仍优先。
- 更新 README 的 PowerShell 配置示例和模型说明。

不修改 DeepSeek Base URL、API Key 读取方式、路由优先级、备用供应商或请求协议。
本次也不将 V4 Pro 引入默认链路。

## 行为与数据流

启动时配置加载器读取 `DEEPSEEK_API_KEY`。存在密钥时创建 DeepSeek endpoint：

1. `DEEPSEEK_MODEL` 未设置时，普通请求选择 `deepseek-v4-flash`。
2. `DEEPSEEK_REASONING_MODEL` 未设置时，深度思考请求也选择
   `deepseek-v4-flash`，现有 thinking 参数逻辑保持不变。
3. 任一环境变量显式设置时，继续使用调用者给出的模型名。

## 错误处理与兼容性

项目不在启动时联网探测模型列表，因此无密钥或服务端拒绝请求时仍沿用现有错误处理。
直接使用正式模型 ID 可避免旧兼容别名弃用后的请求失败。已有部署若设置了模型环境变量，
升级后行为不变。

## 测试与验收

- 先增加默认值测试并确认其在旧实现上失败。
- 修改默认值后确认新测试通过。
- 运行相关配置/架构测试以及项目统一验证脚本。
- README 不再推荐已弃用的两个旧模型名。

