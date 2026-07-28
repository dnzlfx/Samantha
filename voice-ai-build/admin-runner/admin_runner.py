#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import docker


CONFIRMATION = "CONFIRMO_REINICIAR_OPENCLAW"
ALLOWED_ACTIONS = {"openclaw_status", "openclaw_logs_tail", "restart_openclaw"}


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length", "0") or "0")
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


class AdminRunner:
    def __init__(self) -> None:
        self.client = docker.from_env()

    def openclaw_container(self):
        return self.client.containers.get("openclaw")

    def run_action(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS:
            return {"ok": False, "error": "action_not_allowed", "allowed": sorted(ALLOWED_ACTIONS)}
        if action == "openclaw_status":
            c = self.openclaw_container()
            c.reload()
            return {"ok": True, "name": c.name, "status": c.status, "image": c.image.tags}
        if action == "openclaw_logs_tail":
            c = self.openclaw_container()
            tail = int(payload.get("tail", 80) or 80)
            tail = max(1, min(tail, 300))
            logs = c.logs(tail=tail).decode("utf-8", errors="replace")
            return {"ok": True, "tail": tail, "logs": logs}
        if action == "restart_openclaw":
            if payload.get("confirmation") != CONFIRMATION:
                return {"ok": False, "error": "confirmation_required", "required": CONFIRMATION}
            c = self.openclaw_container()
            c.restart(timeout=30)
            c.reload()
            return {"ok": True, "action": "restart_openclaw", "status": c.status}
        return {"ok": False, "error": "unhandled_action"}


class Handler(BaseHTTPRequestHandler):
    runner: AdminRunner | None = None

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("admin-runner " + fmt % args + "\n")

    def _authorized(self) -> bool:
        expected = os.environ.get("VOICE_ADMIN_TOKEN", "")
        got = self.headers.get("x-voice-token", "")
        return bool(expected) and got == expected

    def do_GET(self) -> None:
        if self.path == "/healthz":
            json_response(self, 200, {"ok": True})
            return
        json_response(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/action":
            json_response(self, 404, {"ok": False, "error": "not_found"})
            return
        if not self._authorized():
            json_response(self, 401, {"ok": False, "error": "unauthorized"})
            return
        try:
            payload = read_json(self)
            action = str(payload.get("action", ""))
            if Handler.runner is None:
                Handler.runner = AdminRunner()
            result = Handler.runner.run_action(action, payload)
            json_response(self, 200 if result.get("ok") else 400, result)
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck-once", action="store_true")
    args = parser.parse_args()
    if args.healthcheck_once:
        return 0
    port = int(os.environ.get("PORT", "8088"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"voice-admin-runner listening on {port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
