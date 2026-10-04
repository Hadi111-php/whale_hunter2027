"""
REST API and Gateway Server for Android App & Remote Clients ('Feet' Engine).
Built in pure Python standard library (http.server) for 100% portability, zero required dependencies,
and high performance threading.
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import socketserver
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import AppConfig
from core.approval_guard import ApprovalGuard
from core.brain_router import DualBrainRouter
from core.memory_engine import MemoryEngine
from eyes.desktop_observer import DesktopObserver
from eyes.screen_capture import ScreenCaptureEngine
from feet.static_ip_helper import NetworkHelper
from hands.command_executor import SafeCommandExecutor
from hands.file_manager import SafeFileManager
from hands.input_controller import InputController
from hands.web_operator import WebOperator

logger = logging.getLogger("qwen_hands_eyes.api_server")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class SkyGroundAPIRequestHandler(http.server.BaseHTTPRequestHandler):
    """Handles REST API requests and serves static dashboard assets."""

    server_context: Dict[str, Any] = {}

    def log_message(self, format, *args):
        # Clean logging
        logger.debug(f"{self.address_string()} - {format % args}")

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Agent-Token")

    def _send_json(self, status_code: int, data: Dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/v1/status":
            self._handle_get_status()
        elif path == "/api/v1/eyes/snapshot":
            self._handle_get_snapshot()
        elif path == "/api/v1/approvals":
            self._handle_get_approvals()
        elif path == "/api/v1/memory":
            self._handle_get_memory(parsed_url.query)
        elif path.startswith("/static/"):
            self._serve_static_file(path[8:])
        elif path in {"/", "/index.html"}:
            self._serve_static_file("index.html")
        else:
            self._send_json(404, {"ok": False, "error": "Endpoint not found"})

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8")
            body = json.loads(raw_body) if raw_body else {}
        except Exception as e:
            self._send_json(400, {"ok": False, "error": f"Invalid JSON payload: {e}"})
            return

        if path == "/api/v1/chat":
            self._handle_post_chat(body)
        elif path == "/api/v1/hands/action":
            self._handle_post_hands_action(body)
        elif path == "/api/v1/brain/route":
            self._handle_post_brain_route(body)
        elif path == "/api/v1/search":
            self._handle_post_search(body)
        elif path == "/api/v1/approvals/resolve":
            self._handle_post_approvals_resolve(body)
        else:
            self._send_json(404, {"ok": False, "error": "Endpoint not found"})

    # ══════════════════════════════════════════════════════════════════
    # API HANDLERS
    # ══════════════════════════════════════════════════════════════════

    def _handle_get_status(self) -> None:
        ctx = self.server_context
        config: AppConfig = ctx["config"]
        conn_info = NetworkHelper.get_connection_info(config.feet.port, config.feet.static_ip)

        self._send_json(
            200,
            {
                "ok": True,
                "agent_name": config.agent_name,
                "mode": config.mode,
                "primary_model": config.primary_brain.model,
                "reasoning_model": config.reasoning_brain.model,
                "eyes_enabled": config.eyes.enabled,
                "hands_enabled": config.hands.enabled,
                "feet_enabled": config.feet.enabled,
                "network": conn_info,
                "time": time.time(),
            },
        )

    def _handle_get_snapshot(self) -> None:
        ctx = self.server_context
        observer: DesktopObserver = ctx["desktop_observer"]
        obs = observer.capture_and_inspect()
        self._send_json(200, {"ok": True, "observation": obs})

    def _handle_get_approvals(self) -> None:
        ctx = self.server_context
        guard: ApprovalGuard = ctx["approval_guard"]
        pending = guard.list_pending_requests()
        self._send_json(200, {"ok": True, "pending": pending, "count": len(pending)})

    def _handle_get_memory(self, query_str: str) -> None:
        ctx = self.server_context
        mem: MemoryEngine = ctx["memory"]
        params = urllib.parse.parse_qs(query_str)
        session_id = params.get("session_id", ["default"])[0]
        history = mem.get_conversation_history(session_id, limit=20)
        self._send_json(200, {"ok": True, "history": history})

    def _handle_post_chat(self, body: Dict[str, Any]) -> None:
        ctx = self.server_context
        router: DualBrainRouter = ctx["brain_router"]
        mem: MemoryEngine = ctx["memory"]

        message = str(body.get("message", "")).strip()
        session_id = str(body.get("session_id", "default"))
        force_brain = body.get("force_brain")

        if not message:
            self._send_json(400, {"ok": False, "error": "Message cannot be empty"})
            return

        # Save user message in memory
        mem.save_message(session_id, "user", message)

        # Retrieve recent memory context & relevant experiences
        history = mem.get_conversation_history(session_id, limit=6)
        experiences = mem.search_experiences(message, limit=3)

        context_parts = []
        if experiences:
            context_parts.append("Learned Experiences:")
            for exp in experiences:
                context_parts.append(f"- [{exp['category']}] {exp['title']}: {exp['content']}")

        context_str = "\n".join(context_parts) if context_parts else None

        # Execute dual brain processing
        res = router.process(
            message=message,
            conversation_history=history,
            context=context_str,
            force_brain=force_brain,
        )

        # Save assistant reply in memory
        mem.save_message(
            session_id,
            "assistant",
            res.get("response", ""),
            metadata={"routed_to": res.get("routed_to"), "thought": res.get("thought_process")},
        )

        self._send_json(200, {"ok": True, "result": res})

    def _handle_post_hands_action(self, body: Dict[str, Any]) -> None:
        ctx = self.server_context
        controller: InputController = ctx["input_controller"]
        executor: SafeCommandExecutor = ctx["command_executor"]
        file_mgr: SafeFileManager = ctx["file_manager"]
        web_op: WebOperator = ctx["web_operator"]

        action_type = str(body.get("action_type", "")).lower()
        params = body.get("params", {})

        if action_type == "move":
            res = controller.move_to(int(params.get("x", 0)), int(params.get("y", 0)))
        elif action_type == "click":
            x = int(params["x"]) if "x" in params else None
            y = int(params["y"]) if "y" in params else None
            res = controller.click(x=x, y=y, button=str(params.get("button", "left")), clicks=int(params.get("clicks", 1)))
        elif action_type == "type":
            res = controller.type_text(str(params.get("text", "")))
        elif action_type == "hotkey":
            keys = params.get("keys", [])
            res = controller.hotkey(*keys)
        elif action_type == "scroll":
            res = controller.scroll(int(params.get("clicks", 0)))
        elif action_type == "command":
            res = executor.execute(str(params.get("command", "")), cwd=params.get("cwd"))
        elif action_type == "file_read":
            res = file_mgr.read_file(str(params.get("path", "")))
        elif action_type == "file_write":
            res = file_mgr.write_file(str(params.get("path", "")), str(params.get("content", "")))
        elif action_type == "file_edit":
            res = file_mgr.edit_file(str(params.get("path", "")), str(params.get("old_text", "")), str(params.get("new_text", "")))
        elif action_type == "file_list":
            res = file_mgr.list_files(str(params.get("dir", ".")), pattern=str(params.get("pattern", "*")))
        elif action_type == "search":
            res = web_op.search(str(params.get("query", "")))
        elif action_type == "fetch_page":
            res = web_op.fetch_page_content(str(params.get("url", "")))
        else:
            res = {"ok": False, "error": f"Unknown action type: '{action_type}'"}

        self._send_json(200, res)

    def _handle_post_brain_route(self, body: Dict[str, Any]) -> None:
        ctx = self.server_context
        router: DualBrainRouter = ctx["brain_router"]
        mode = body.get("mode")
        if mode:
            res = router.set_mode(str(mode))
            self._send_json(200, res)
        else:
            self._send_json(400, {"ok": False, "error": "Missing 'mode' field in payload"})

    def _handle_post_search(self, body: Dict[str, Any]) -> None:
        ctx = self.server_context
        web_op: WebOperator = ctx["web_operator"]
        query = str(body.get("query", "")).strip()
        if not query:
            self._send_json(400, {"ok": False, "error": "Query cannot be empty"})
            return
        res = web_op.search(query, max_results=int(body.get("max_results", 5)))
        self._send_json(200, res)

    def _handle_post_approvals_resolve(self, body: Dict[str, Any]) -> None:
        ctx = self.server_context
        guard: ApprovalGuard = ctx["approval_guard"]
        req_id = str(body.get("request_id", ""))
        approved = bool(body.get("approved", False))
        success = guard.resolve_request(req_id, approved=approved, decision_by="web_api")
        self._send_json(200, {"ok": success, "request_id": req_id, "approved": approved})

    def _serve_static_file(self, filename: str) -> None:
        static_dir = Path(__file__).parent.parent / "dashboard" / "static"
        target_path = (static_dir / filename).resolve()
        try:
            target_path.relative_to(static_dir)
        except ValueError:
            self._send_json(403, {"ok": False, "error": "Forbidden path"})
            return

        if not target_path.exists() or not target_path.is_file():
            self._send_json(404, {"ok": False, "error": f"File '{filename}' not found"})
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
        }
        ext = target_path.suffix.lower()
        content_type = content_types.get(ext, "application/octet-stream")

        data = target_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(data)


class APIGatewayServer:
    """Manages the lifecycle of the HTTP and WebSocket API Gateway."""

    def __init__(self, context: Dict[str, Any], host: str = "0.0.0.0", port: int = 8765):
        self.context = context
        self.host = host
        self.port = port
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self, block: bool = False) -> None:
        SkyGroundAPIRequestHandler.server_context = self.context
        self.httpd = ThreadingHTTPServer((self.host, self.port), SkyGroundAPIRequestHandler)
        logger.info(f"🚀 SkyGround API & Dashboard running on http://{self.host}:{self.port}")

        if block:
            try:
                self.httpd.serve_forever()
            except KeyboardInterrupt:
                self.stop()
        else:
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.thread.start()

    def stop(self) -> None:
        if self.httpd:
            logger.info("Stopping SkyGround Gateway Server...")
            self.httpd.shutdown()
            self.httpd.server_close()
