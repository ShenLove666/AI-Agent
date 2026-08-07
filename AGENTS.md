# 识图能力

底层模型不具备原生识图能力。遇到图片时，**不要用 Read 工具**，改用 vision.js：

```
node vision.js "<图片路径>" "用中文描述这张图片"
```

## 触发场景

- 用户分享图片路径（本地或网络 URL）
- 消息中出现 "Saved attachments:" 并列出图片
- 用户要求分析、描述、识别图片内容

## 配置

- `vision.js` 读取同目录 `.env` 文件（`DASHSCOPE_BASE_URL` / `DASHSCOPE_API_KEY` / `VISION_MODEL`）
- 当前使用小米 MiMo v2.5（`mimo-v2.5`），官方 API `https://api.xiaomimimo.com/v1`
- 支持本地图片路径或 `--url` 远程图片链接
