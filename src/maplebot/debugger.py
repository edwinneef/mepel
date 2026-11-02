import json
import re
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlparse

from .contracts import CommandGate
from .overlay_session import OverlaySession
from .runtime import Application


def serve(
    app: Application,
    port: int,
    *,
    on_restart: Callable[[], None] | None = None,
    on_shutdown: Callable[[], None] | None = None,
) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(32)
    instance_id = secrets.token_hex(12)
    command_gate = CommandGate()
    overlay = OverlaySession(app)
    app.overlay = overlay

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self) -> bool:
            host = self.headers.get("Host", "")
            return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def do_GET(self) -> None:
            if not self.allowed():
                self.reply(403, b"Loopback host required", "text/plain")
                return
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/legacy"}:
                static = files("maplebot").joinpath("static")
                workbench = static.joinpath("workbench/index.html")
                page = workbench if parsed.path == "/" and workbench.is_file() \
                    else static.joinpath("index.html")
                html = page.read_text("utf-8")
                self.reply(
                    200, html.replace("__TOKEN__", token).encode(), "text/html; charset=utf-8"
                )
            elif re.fullmatch(r"/assets/[A-Za-z0-9_.-]+\.(js|css)", parsed.path):
                asset = files("maplebot").joinpath("static/workbench" + parsed.path)
                if not asset.is_file():
                    self.reply(404, b"Asset not found", "text/plain")
                    return
                kind = "text/css" if parsed.path.endswith(".css") else "text/javascript"
                self.reply(200, asset.read_bytes(), kind)
            elif parsed.path in {"/api/status", "/api/v1/status"}:
                status = {
                    **app.snapshot(),
                    "instance_id": instance_id,
                    "restart_available": on_restart is not None,
                    "shutdown_available": on_shutdown is not None,
                }
                self.reply(200, json.dumps(status).encode(), "application/json")
            elif parsed.path == "/api/v1/drawings":
                self.reply(200, json.dumps(app.drawings()).encode(), "application/json")
            elif parsed.path == "/api/v1/area-frame":
                query = parse_qs(parsed.query)
                body = app.areas.frame(query.get("id", [""])[0])
                self.reply(200 if body else 404, body or b"Reference image unavailable",
                           "image/png" if body else "text/plain")
            elif parsed.path == "/api/v1/preview":
                query = parse_qs(parsed.query)
                body = app.preview_frame(query.get("id", [""])[0])
                self.reply(200 if body else 409, body or b"Frame superseded", "image/png"
                           if body else "text/plain")
            elif parsed.path == "/api/v1/frame":
                query = parse_qs(parsed.query)
                body = app.frame(query.get("id", [""])[0], raw="raw" in query)
                self.reply(200 if body else 409, body or b"Frame superseded", "image/png"
                           if body else "text/plain")
            elif parsed.path == "/frame.png":
                key = parse_qs(parsed.query).get("id", [None])[0]
                if key:
                    # Frozen frames are immutable and bounded; serialize access with worker.
                    try:
                        body = app.request("frozen_png", {"id": key})
                    except (KeyError, ValueError):
                        self.reply(404, b"Frozen frame expired", "text/plain")
                        return
                else:
                    with app.lock:
                        body = app.raw if "raw" in parse_qs(parsed.query) else app.latest
                self.reply(200 if body else 204, body or b"", "image/png")
            else:
                self.reply(404, b"Not found", "text/plain")

        def do_POST(self) -> None:
            if not self.allowed() or self.headers.get("X-Debug-Token") != token:
                self.reply(403, b"Invalid local debugger token", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 1_000_000 if self.path in {"/api/v1/command", "/api/area_save"} else 16384
                if not 0 < length <= limit:
                    raise ValueError("Invalid request length")
                payload = json.loads(self.rfile.read(length))
                if self.path == "/api/overlay_close":
                    result = overlay.request_close()
                    self.reply(200, json.dumps(result).encode(), "application/json")
                    return
                if self.path == "/api/overlay":
                    result = overlay.heartbeat(payload)
                    self.reply(200, json.dumps(result).encode(), "application/json")
                    return
                if self.path == "/api/overlay_companion":
                    if not isinstance(payload, dict):
                        raise ValueError("Widget payload must be an object")
                    result = overlay.companion_heartbeat(payload)
                    self.reply(200, json.dumps(result).encode(), "application/json")
                    return
                if self.path in {"/api/dashboard", "/api/dashboard_disconnect"}:
                    if not isinstance(payload, dict):
                        raise ValueError("Dashboard payload must be an object")
                    result = overlay.dashboard_heartbeat(payload) if self.path == "/api/dashboard" \
                        else overlay.dashboard_disconnect(payload)
                    self.reply(200, json.dumps(result).encode(), "application/json")
                    return
                command = self.path.removeprefix("/api/")
                context = None
                versioned = self.path == "/api/v1/command"
                if versioned:
                    command, payload, context = command_gate.accept(payload, app.snapshot())
                elif not isinstance(payload, dict):
                    raise ValueError("Command payload must be an object")
                if length > 16384 and command != "area_save":
                    raise ValueError("Invalid request length")
                if command in {"restart_bot", "shutdown_bot"}:
                    callback = on_restart if command == "restart_bot" else on_shutdown
                    if callback is None:
                        raise RuntimeError("Process control is unavailable in this session")
                    restarting = command == "restart_bot"
                    app.safe_stop(
                        "OPERATOR_STOP",
                        "Bot restart requested" if restarting else "Server shutdown requested",
                    )
                    # A peer can disconnect while the acknowledgement is being written.
                    # Once input is stopped, process shutdown must not depend on that write.
                    callback()
                    self.reply(
                        200,
                        json.dumps({
                            "restarting" if restarting else "stopping": True,
                            "instance_id": instance_id,
                        }).encode(),
                        "application/json",
                    )
                    return
                elif command == "acknowledge":
                    result = app.acknowledge_stop(payload.get("incident_id"), require_id=True)
                elif command == "restart_capture":
                    result = app.restart_capture()
                else:
                    result = app.request(command, payload, context=context) if versioned \
                        else app.request(command, payload)
                self.reply(200, json.dumps(result).encode(), "application/json")
            except Exception as error:
                self.reply(400, json.dumps({"error": str(error)}).encode(), "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, name="debugger", daemon=True).start()
    return server
