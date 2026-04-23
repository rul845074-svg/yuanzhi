#!/usr/bin/env bash
# 双击启动认知镜本地服务（前端 + API）
# - 前端看板 + 运行分析：http://127.0.0.1:8773
# - 关闭：在终端窗口里按 Ctrl+C，或直接关窗口

set -e

cd "$(dirname "$0")/scripts"

# 若 8773 已被占用（上次没退干净），先提示一声
if lsof -nP -iTCP:8773 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⚠️  端口 8773 已被占用，先打开浏览器即可；若想重启服务，请先 kill 已有进程。"
  open "http://127.0.0.1:8773/"
  exit 0
fi

echo "▶ 启动认知镜本地服务（端口 8773，prod profile）..."
# 后台延时 2 秒再打开浏览器，等服务起来
( sleep 2 && open "http://127.0.0.1:8773/" ) &

exec python3 serve_cognitive_agent_demo.py --profile prod --no-auto-refresh --port 8773
