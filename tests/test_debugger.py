import json
import re
import threading
import time
from http.client import HTTPConnection
from importlib.resources import files

import pytest

from maplebot.debugger import serve


class RestartApp:
    def __init__(self):
        self.events = []
        self.held = {"up"}

    def snapshot(self):
        return {"state": "IDLE", "capture_only": True}

    def safe_stop(self, code, message):
        assert code == "OPERATOR_STOP"
        self.held.clear()
        self.events.append("released")


def request(server, method, path, token=None, payload=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    headers = {"Host": "127.0.0.1:0"}
    if token is not None:
        headers["X-Debug-Token"] = token
    try:
        connection.request(
            method, path, body=json.dumps(payload or {}) if method == "POST" else None,
            headers=headers,
        )
        response = connection.getresponse()
        return response.status, response.read().decode()
    finally:
        connection.close()


def test_read_only_preview_route_requires_the_matching_frame_id():
    app = RestartApp()
    app.preview_frame = lambda frame_id: b"PNG" if frame_id == "preview:1" else None
    server = serve(app, 0)
    try:
        assert request(server, "GET", "/api/v1/preview?id=preview:1") == (200, "PNG")
        assert request(server, "GET", "/api/v1/preview?id=old")[0] == 409
        assert app.events == []
    finally:
        server.shutdown()
        server.server_close()


def test_display_drawings_route_returns_the_latest_packet_or_null():
    app = RestartApp()
    packets = [None, {"display": True, "frame": {"id": "s:source:0:display:1"}}]
    app.drawings = lambda: packets.pop(0)
    server = serve(app, 0)
    try:
        assert request(server, "GET", "/api/v1/drawings") == (200, "null")
        status, body = request(server, "GET", "/api/v1/drawings")
        assert status == 200 and json.loads(body)["display"] is True
        assert app.events == []
    finally:
        server.shutdown()
        server.server_close()


def test_area_reference_route_is_read_only_and_rejects_unknown_images(tmp_path):
    from maplebot.profiles import AreaStore

    app = RestartApp()
    app.areas = AreaStore(tmp_path / "areas")
    app.areas.frame = lambda image_id: b"PNG" if image_id == "a" * 64 else None
    server = serve(app, 0)
    try:
        assert request(server, "GET", "/api/v1/area-frame?id=" + "a" * 64) == (200, "PNG")
        assert request(server, "GET", "/api/v1/area-frame?id=../config")[0] == 404
        assert app.events == []
    finally:
        server.shutdown()
        server.server_close()


def test_only_area_save_accepts_a_profile_larger_than_the_normal_command_limit():
    app = RestartApp()
    calls = []
    app.snapshot = lambda: {"session_id": "session", "command_epoch": 1}
    app.request = lambda name, payload, **kwargs: calls.append(name) or {"ok": True}
    server = serve(app, 0)
    try:
        _, page = request(server, "GET", "/legacy")
        token = re.search(r"const token='([^']+)'", page)[1]
        envelope = {
            "schema_version": 1, "session_id": "session", "command_epoch": 1,
            "command_id": "large-area-save", "issued_at": time.time(),
            "name": "area_save", "payload": {"profile": "x" * 20000},
        }
        assert request(server, "POST", "/api/v1/command", token, envelope)[0] == 200
        envelope.update(name="windows", command_id="large-other-command")
        assert request(server, "POST", "/api/v1/command", token, envelope)[0] == 400
        assert calls == ["area_save"]
    finally:
        server.shutdown()
        server.server_close()


def test_restart_releases_keys_and_returns_the_instance_before_restarting():
    app = RestartApp()
    restarted = threading.Event()

    def on_restart():
        app.events.append("restart")
        restarted.set()

    server = serve(app, 0, on_restart=on_restart)
    try:
        _, page = request(server, "GET", "/legacy")
        token = re.search(r"const token='([^']+)'", page)[1]
        _, status = request(server, "GET", "/api/status")
        code, body = request(server, "POST", "/api/restart_bot", token)

        assert code == 200
        assert json.loads(body)["restarting"]
        assert json.loads(body)["instance_id"] == json.loads(status)["instance_id"]
        assert restarted.wait(1)
        assert app.held == set()
        assert app.events == ["released", "restart"]
    finally:
        server.shutdown()
        server.server_close()


def test_restart_requires_the_debugger_token():
    app = RestartApp()
    server = serve(app, 0, on_restart=lambda: app.events.append("restart"))
    try:
        code, _ = request(server, "POST", "/api/restart_bot", "invalid")
        assert code == 403
        assert app.events == []
    finally:
        server.shutdown()
        server.server_close()


def test_versioned_commands_reject_stale_and_duplicate_requests_before_dispatch():
    app = RestartApp()
    calls = []
    app.snapshot = lambda: {
        "session_id": "current", "command_epoch": 1,
        "frame": {"id": "current:1", "available": True, "age_ms": 10},
    }
    app.request = lambda name, payload, *, context: calls.append(name) or {"ok": True}
    server = serve(app, 0)
    try:
        _, page = request(server, "GET", "/legacy")
        token = re.search(r"const token='([^']+)'", page)[1]
        payload = {
            "schema_version": 1, "session_id": "current", "command_epoch": 1,
            "issued_at": time.time(), "command_id": "unique-command", "name": "dry_run",
            "expected_frame_id": "old", "payload": {},
        }
        assert request(server, "POST", "/api/v1/command", token, payload)[0] == 400
        assert calls == []
        payload["expected_frame_id"] = "current:1"
        assert request(server, "POST", "/api/v1/command", token, payload)[0] == 200
        assert request(server, "POST", "/api/v1/command", token, payload)[0] == 400
        assert calls == ["dry_run"]
    finally:
        server.shutdown()
        server.server_close()


def test_workbench_and_legacy_share_token_but_only_packaged_assets_are_served():
    bundle = files("maplebot").joinpath("static/workbench/index.html")
    if not bundle.is_file():
        pytest.skip("Build the React workbench before checking bundle serving")
    server = serve(RestartApp(), 0)
    try:
        code, page = request(server, "GET", "/")
        assert code == 200
        assert '__TOKEN__' not in page
        assert 'name="debug-token"' in page
        code, legacy = request(server, "GET", "/legacy")
        token = re.search(r"const token='([^']+)'", legacy)[1]
        assert token in page
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page)
        assert assets
        for asset in assets:
            assert request(server, "GET", asset)[0] == 200
        for path in ("/assets/../index.html", "/assets/%2e%2e/config.toml", "/assets/missing.js"):
            assert request(server, "GET", path)[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_restart_is_unavailable_when_the_server_has_no_process_supervisor():
    app = RestartApp()
    server = serve(app, 0)
    try:
        _, page = request(server, "GET", "/legacy")
        token = re.search(r"const token='([^']+)'", page)[1]
        _, status = request(server, "GET", "/api/status")
        assert json.loads(status)["restart_available"] is False
        code, body = request(server, "POST", "/api/restart_bot", token)
        assert code == 400
        assert "unavailable" in json.loads(body)["error"].lower()
        assert app.events == []
    finally:
        server.shutdown()
        server.server_close()


def test_http_acknowledgement_requires_the_displayed_incident_id():
    app = RestartApp()
    calls = []

    def acknowledge(incident_id, *, require_id):
        calls.append((incident_id, require_id))
        return {"acknowledged": incident_id == "current" and require_id}

    app.acknowledge_stop = acknowledge
    server = serve(app, 0)
    try:
        _, page = request(server, "GET", "/legacy")
        token = re.search(r"const token='([^']+)'", page)[1]
        for incident_id in (None, "old", "current"):
            payload = {} if incident_id is None else {"incident_id": incident_id}
            code, body = request(server, "POST", "/api/acknowledge", token, payload)
            assert code == 200
            assert json.loads(body)["acknowledged"] is (incident_id == "current")
        assert calls == [(None, True), ("old", True), ("current", True)]
    finally:
        server.shutdown()
        server.server_close()


def test_shutdown_releases_keys_then_signals_process_exit():
    app = RestartApp()
    stopped = threading.Event()
    server = serve(app, 0, on_shutdown=stopped.set)
    try:
        _, page = request(server, "GET", "/legacy")
        token = re.search(r"const token='([^']+)'", page)[1]
        _, status = request(server, "GET", "/api/status")
        assert json.loads(status)["shutdown_available"] is True
        code, body = request(server, "POST", "/api/shutdown_bot", token)
        assert code == 200
        assert json.loads(body)["stopping"] is True
        assert stopped.wait(1)
        assert app.held == set()
        assert app.events == ["released"]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("available,token", [(True, "invalid"), (False, None)])
def test_shutdown_rejects_invalid_tokens_and_missing_supervision(available, token):
    app = RestartApp()
    stopped = threading.Event()
    server = serve(app, 0, on_shutdown=stopped.set if available else None)
    try:
        if token is None:
            _, page = request(server, "GET", "/legacy")
            token = re.search(r"const token='([^']+)'", page)[1]
        code, _ = request(server, "POST", "/api/shutdown_bot", token)
        assert code == (403 if available else 400)
        assert not stopped.is_set()
        assert app.events == []
    finally:
        server.shutdown()
        server.server_close()
