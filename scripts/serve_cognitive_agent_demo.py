#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cognitive_agent_runtime import (
    CLAUDE_TASKS,
    get_agent_status,
    get_progress,
    get_workbench_payload,
    list_reminders,
    run_demo,
    run_task,
    task_registry,
    update_reminder_status,
)

from concept_review import list_concept_candidates, review_concept


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DIST_ROOT = WORKSPACE_ROOT / "apps" / "cognitive-mirror-preview" / "dist"
MIRROR_SCALE_PATH = WORKSPACE_ROOT / "data" / "generated" / "mirror-scale.json"


class AgentDemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, profile: str | None = None, **kwargs):
        self.profile = profile
        super().__init__(*args, directory=str(DIST_ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _handle_api_get(self, parsed) -> bool:
        if parsed.path == "/api/health":
            status = get_agent_status()
            self._send_json(
                {
                    "ok": True,
                    "profile": self.profile,
                    "dist_root": str(DIST_ROOT),
                    "available_tasks": [task["name"] for task in status["available_tasks"]],
                    "last_run": status.get("last_run"),
                }
            )
            return True

        if parsed.path == "/api/workbench":
            payload = get_workbench_payload(profile=self.profile, refresh_if_missing=True)
            self._send_json(payload)
            return True

        if parsed.path == "/api/mirror-scale":
            if MIRROR_SCALE_PATH.exists():
                try:
                    payload = json.loads(MIRROR_SCALE_PATH.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    self._send_json({"error": f"invalid mirror-scale.json: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    return True
                self._send_json(payload)
            else:
                self._send_json({"error": "mirror-scale.json not found; run scripts/generate_frontend_scale.py"}, status=HTTPStatus.NOT_FOUND)
            return True

        if parsed.path == "/api/agent/status":
            self._send_json(get_agent_status())
            return True

        if parsed.path == "/api/agent/tasks":
            self._send_json({"tasks": list(task_registry().values())})
            return True

        if parsed.path == "/api/reminders":
            self._send_json(list_reminders(profile=self.profile, refresh_if_missing=True))
            return True

        if parsed.path == "/api/agent/progress":
            self._send_json(get_progress())
            return True

        if parsed.path == "/api/concepts/candidates":
            self._send_json(list_concept_candidates(profile=self.profile))
            return True

        if parsed.path == "/api/agent/run":
            query = parse_qs(parsed.query)
            task = query.get("task", ["demo"])[0]
            profile = query.get("profile", [self.profile])[0]
            date = query.get("date", [None])[0]
            if task == "demo":
                result = run_demo(profile=profile)
            else:
                result = run_task(task_name=task, profile=profile, date_str=date)
            self._send_json(result)
            return True

        return False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if self._handle_api_get(parsed):
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            body = self._read_json_body()
            if parsed.path == "/api/agent/run":
                task = body.get("task", "demo")
                profile = body.get("profile", self.profile)
                date_str = body.get("date")
                if task == "demo":
                    result = run_demo(profile=profile)
                else:
                    result = run_task(task_name=task, profile=profile, date_str=date_str)
                self._send_json(result)
                return
            if parsed.path == "/api/reminders/update":
                result = update_reminder_status(
                    reminder_id=body.get("id", ""),
                    status=body.get("status", ""),
                    profile=body.get("profile", self.profile),
                    snooze_until=body.get("snooze_until"),
                )
                self._send_json(result)
                return
            if parsed.path == "/api/concepts/review":
                result = review_concept(
                    concept_id=body.get("id", ""),
                    action=body.get("action", ""),
                    profile=body.get("profile", self.profile),
                )
                self._send_json(result)
                return
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the cognitive mirror MVP demo with backend agent endpoints.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8773, help="Port to bind.")
    parser.add_argument("--profile", choices=["dev", "prod"], default="dev", help="Config profile to use.")
    parser.add_argument(
        "--no-auto-refresh",
        action="store_true",
        help="Do not refresh the demo payload on startup.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.no_auto_refresh:
        run_demo(profile=args.profile)

    handler = partial(AgentDemoHandler, profile=args.profile)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Cognitive agent demo running on http://{args.host}:{args.port}")
    print("API endpoints:")
    print(f"- http://{args.host}:{args.port}/api/health")
    print(f"- http://{args.host}:{args.port}/api/workbench")
    print(f"- http://{args.host}:{args.port}/api/mirror-scale")
    print(f"- http://{args.host}:{args.port}/api/agent/status")
    print(f"- http://{args.host}:{args.port}/api/agent/run?task=demo")
    print(f"- http://{args.host}:{args.port}/api/reminders")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
