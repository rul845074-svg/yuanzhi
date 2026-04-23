#!/usr/bin/env python3
"""Thin cloud API server for Cognitive Mirror dashboard.

Serves static frontend + JSON data files + review/reminder operations.
All state is stored in JSON files under /opt/cognitive-mirror/data/.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA_DIR = Path("/opt/cognitive-mirror/data")
DIST_DIR = Path("/opt/cognitive-mirror/dist")
PENDING_ACTIONS = DATA_DIR / "pending_actions.json"
LOCAL_TUNNEL_PORT = 8774  # reverse SSH tunnel from user's local machine


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat(timespec="seconds")


def read_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class CloudHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def log_message(self, format, *args):
        return

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        from urllib.parse import urlparse
        parsed = urlparse(self.path)

        if parsed.path == "/api/health":
            self._send_json({"ok": True, "mode": "cloud"})
            return

        if parsed.path == "/api/concepts/candidates":
            self._send_json(read_json(DATA_DIR / "concept_candidates.json", {"candidates": []}))
            return

        if parsed.path == "/api/reminders":
            self._send_json(read_json(DATA_DIR / "reminders.json", {"items": []}))
            return

        if parsed.path == "/api/state/latest":
            # Find most recent daily_state file
            states = sorted(DATA_DIR.glob("daily_state_*.json"), reverse=True)
            if states:
                self._send_json(read_json(states[0]))
            else:
                self._send_json({})
            return

        if parsed.path == "/api/mirror-scale":
            # 规模快照（reports / material_library / knowledge_graph / generated_at）
            # 由本地 generate_frontend_scale.py 生成后经 sync_to_cloud.sh 推到云端
            payload = read_json(DATA_DIR / "mirror-scale.json", None)
            if payload is None:
                self._send_json({"error": "mirror-scale.json not found on cloud; run sync_to_cloud.sh locally"}, HTTPStatus.NOT_FOUND)
            else:
                self._send_json(payload)
            return

        if parsed.path == "/api/agent/progress":
            # 转发到本地反向 SSH 隧道，看本机正在跑什么任务
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{LOCAL_TUNNEL_PORT}/api/agent/progress",
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                self._send_json(result)
            except urllib.error.URLError:
                self._send_json(
                    {"step": 0, "total": 0, "label": "本地隧道未连接", "status": "idle"},
                    HTTPStatus.OK,
                )
            return

        # Static files
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        from urllib.parse import urlparse
        parsed = urlparse(self.path)
        try:
            body = self._read_body()

            if parsed.path == "/api/concepts/review":
                # Store as pending action for local to pull
                action = {
                    "type": "concept_review",
                    "id": body.get("id", ""),
                    "action": body.get("action", ""),
                    "created_at": now_iso(),
                }
                pending = read_json(PENDING_ACTIONS, {"actions": []})
                pending["actions"].append(action)
                pending["updated_at"] = now_iso()
                write_json(PENDING_ACTIONS, pending)

                # Also update local copy for immediate UI feedback
                cands = read_json(DATA_DIR / "concept_candidates.json", {"candidates": []})
                for c in cands.get("candidates", []):
                    if c.get("id") == body.get("id"):
                        c["status"] = "approved" if body.get("action") == "approve" else "rejected"
                        c["reviewed_at"] = now_iso()
                        break
                write_json(DATA_DIR / "concept_candidates.json", cands)

                self._send_json({"ok": True, "action": action})
                return

            if parsed.path == "/api/reminders/update":
                action = {
                    "type": "reminder_update",
                    "id": body.get("id", ""),
                    "status": body.get("status", ""),
                    "created_at": now_iso(),
                }
                pending = read_json(PENDING_ACTIONS, {"actions": []})
                pending["actions"].append(action)
                pending["updated_at"] = now_iso()
                write_json(PENDING_ACTIONS, pending)
                self._send_json({"ok": True, "action": action})
                return

            if parsed.path == "/api/agent/run":
                # Forward to local machine via reverse SSH tunnel
                try:
                    raw = json.dumps(body).encode("utf-8")
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{LOCAL_TUNNEL_PORT}/api/agent/run",
                        data=raw,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=600) as resp:
                        result = json.loads(resp.read().decode("utf-8"))
                    self._send_json(result)
                except urllib.error.URLError:
                    self._send_json(
                        {"error": "local_unreachable", "message": "本地隧道未连接，请先在本地运行 SSH 隧道"},
                        HTTPStatus.BAD_GATEWAY,
                    )
                return

            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        except Exception as e:
            self._send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    host, port = "0.0.0.0", 8773
    server = ThreadingHTTPServer((host, port), CloudHandler)
    print(f"Cloud API running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
