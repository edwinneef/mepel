import json
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlparse

from .runtime import Application


def serve(
    app: Application, port: int, *, on_restart: Callable[[], None] | None = None
) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(32)
    instance_id = secrets.token_hex(12)

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
            if parsed.path == "/":
                html = files("maplebot").joinpath("static/index.html").read_text("utf-8")
                self.reply(
                    200, html.replace("__TOKEN__", token).encode(), "text/html; charset=utf-8"
                )
            elif parsed.path == "/api/status":
                status = {
                    **app.snapshot(),
                    "instance_id": instance_id,
                    "restart_available": on_restart is not None,
                }
                self.reply(200, json.dumps(status).encode(), "application/json")
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
                if not 0 < length <= 16384:
                    raise ValueError("Invalid request length")
                payload = json.loads(self.rfile.read(length))
                command = self.path.removeprefix("/api/")
                if command == "restart_bot":
                    if on_restart is None:
                        raise RuntimeError("Bot restart is unavailable in this session")
                    app.safe_stop("OPERATOR_STOP", "Bot restart requested")
                    self.reply(
                        200,
                        json.dumps({"restarting": True, "instance_id": instance_id}).encode(),
                        "application/json",
                    )
                    on_restart()
                    return
                elif command == "acknowledge":
                    result = app.acknowledge_stop(payload.get("incident_id"), require_id=True)
                elif command == "restart_capture":
                    result = app.restart_capture()
                else:
                    result = app.request(command, payload)
                self.reply(200, json.dumps(result).encode(), "application/json")
            except Exception as error:
                self.reply(400, json.dumps({"error": str(error)}).encode(), "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, name="debugger", daemon=True).start()
    return server
