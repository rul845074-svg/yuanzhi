#!/usr/bin/env bash
# Sync local 元知 build + state + api_server to cloud server
# Usage: ./sync_to_cloud.sh [--api-only|--dist-only|--data-only]
#
# 架构：
#   - /opt/cognitive-mirror/dist/        ← 前端静态文件（新 A 纸本 index.html + assets）
#   - /opt/cognitive-mirror/data/        ← 数据 JSON（mirror-scale + concept candidates + reminders + daily state）
#   - /opt/cognitive-mirror/api_server.py ← 云端薄 API（serve dist + serve data + 转发到本地反向隧道）

set -euo pipefail

CLOUD_USER="ubuntu"
CLOUD_HOST="43.157.16.146"
CLOUD_ROOT="/opt/cognitive-mirror"
CLOUD_DIST="$CLOUD_ROOT/dist"
CLOUD_DATA="$CLOUD_ROOT/data"

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_DIST="$WORKSPACE/apps/cognitive-mirror-preview/dist"
LOCAL_API="$WORKSPACE/deploy/cloud/api_server.py"
LOCAL_MIRROR_SCALE="$WORKSPACE/data/generated/mirror-scale.json"
VAULT_STATE="/Users/zhanghu/Library/Mobile Documents/iCloud~md~obsidian/Documents/待建思维系统/可实现/系统状态"

MODE="${1:-all}"

echo "=== Syncing to cloud ($CLOUD_HOST) · mode=$MODE ==="

# ─── 1. 前端 dist 全量 ───
if [ "$MODE" = "all" ] || [ "$MODE" = "--dist-only" ]; then
  echo "[dist] Pushing frontend (index.html + assets/)…"
  ssh "$CLOUD_USER@$CLOUD_HOST" "sudo mkdir -p $CLOUD_DIST && sudo chown -R $CLOUD_USER:$CLOUD_USER $CLOUD_DIST"
  # 推整个 dist，覆盖云端旧 React SPA
  rsync -az --delete "$LOCAL_DIST/" "$CLOUD_USER@$CLOUD_HOST:$CLOUD_DIST/"
fi

# ─── 2. 数据 JSON（vault state + mirror-scale）───
if [ "$MODE" = "all" ] || [ "$MODE" = "--data-only" ]; then
  echo "[data] Pushing mirror-scale + vault state…"
  ssh "$CLOUD_USER@$CLOUD_HOST" "sudo mkdir -p $CLOUD_DATA && sudo chown -R $CLOUD_USER:$CLOUD_USER $CLOUD_DATA"
  # 规模快照（新前端消费）
  if [ -f "$LOCAL_MIRROR_SCALE" ]; then
    scp "$LOCAL_MIRROR_SCALE" "$CLOUD_USER@$CLOUD_HOST:$CLOUD_DATA/mirror-scale.json"
  else
    echo "  ⚠ mirror-scale.json 不存在，先跑 python3 scripts/generate_frontend_scale.py"
  fi
  # vault state（老 SPA 残留 + 云端读的快照）
  scp "$VAULT_STATE/concept_candidates.json" "$CLOUD_USER@$CLOUD_HOST:$CLOUD_DATA/" 2>/dev/null || echo "  ⚠ concept_candidates.json 缺"
  scp "$VAULT_STATE"/daily_state_*.json "$CLOUD_USER@$CLOUD_HOST:$CLOUD_DATA/" 2>/dev/null || true
  scp "$VAULT_STATE/reminders.json" "$CLOUD_USER@$CLOUD_HOST:$CLOUD_DATA/" 2>/dev/null || true
fi

# ─── 3. 云端 API server（改动时才推，加完 endpoint 必须手动重启进程）───
if [ "$MODE" = "all" ] || [ "$MODE" = "--api-only" ]; then
  echo "[api] Pushing api_server.py…"
  scp "$LOCAL_API" "$CLOUD_USER@$CLOUD_HOST:/tmp/api_server.py.new"
  ssh "$CLOUD_USER@$CLOUD_HOST" "sudo mv /tmp/api_server.py.new $CLOUD_ROOT/api_server.py && sudo chown $CLOUD_USER:$CLOUD_USER $CLOUD_ROOT/api_server.py"
  echo ""
  echo "  ⚠ api_server.py 已更新，但进程还在跑老代码。"
  echo "    手动重启：ssh $CLOUD_USER@$CLOUD_HOST"
  echo "    然后：sudo systemctl restart cognitive-mirror-api  (如果有 service unit)"
  echo "      或：pkill -f api_server.py && sudo nohup python3 $CLOUD_ROOT/api_server.py >/var/log/cm-api.log 2>&1 &"
  echo ""
fi

# ─── 4. 验证 ───
echo "[verify] Cloud endpoints…"
echo "  health:       $(curl -s --max-time 5 http://$CLOUD_HOST/api/health || echo 'unreachable')"
echo "  mirror-scale: $(curl -s --max-time 5 http://$CLOUD_HOST/api/mirror-scale | head -c 100 || echo 'unreachable') …"

echo ""
echo "=== Done ==="
echo "浏览器打开：http://$CLOUD_HOST"
