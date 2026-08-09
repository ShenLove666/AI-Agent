#!/usr/bin/env bash
# 部署脚本：同步代码到服务器并重启服务
# 用法: bash scripts/deploy.sh [目标目录]   (默认 rag-project-20260809-runtime-settings-v5)
set -euo pipefail

SERVER="sdu"
TARGET="${1:-rag-project-20260809-runtime-settings-v5}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="/home/sj/$TARGET"

echo "==> 同步代码到 $SERVER:$REMOTE"
tar czf - \
  --exclude=.git \
  --exclude=.venv \
  --exclude=node_modules \
  --exclude=.cache \
  --exclude=.pytest_cache \
  --exclude=.ruff_cache \
  --exclude=.worktrees \
  --exclude=logs \
  --exclude=data \
  --exclude=models \
  --exclude='*.db' \
  --exclude=rag-project.zip \
  --exclude='.server-*.log' \
  --exclude='.tmp-server-*.log' \
  --exclude='.codex_probe_write_test.txt' \
  --exclude='.env' \
  -C "$ROOT" . | ssh "$SERVER" "mkdir -p '$REMOTE' && tar xzf - -C '$REMOTE'"

echo "==> 重启服务"
ssh "$SERVER" "cd '$REMOTE' && PID=\$(ss -tlnp 2>/dev/null | grep 8081 | grep -oP 'pid=\K[0-9]+' | head -1) && [ -n \"\$PID\" ] && kill \$PID || true; sleep 2; (nohup .venv/bin/python -u server.py > logs/server.log 2>&1 < /dev/null &); sleep 10"

echo "==> 健康检查"
ssh "$SERVER" "curl -s -m 5 http://127.0.0.1:8081/api/v1/health | head -c 120; echo"

echo "==> 完成"
