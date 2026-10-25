import json
import re
import threading
from http.client import HTTPConnection

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


def test_restart_releases_keys_and_returns_the_instance_before_restarting():
    app = RestartApp()
    restarted = threading.Event()

    def on_restart():
        app.events.append("restart")
        restarted.set()

    server = serve(app, 0, on_restart=on_restart)
    try:
        _, page = request(server, "GET", "/")
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


def test_restart_is_unavailable_when_the_server_has_no_process_supervisor():
    app = RestartApp()
    server = serve(app, 0)
    try:
        _, page = request(server, "GET", "/")
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
        _, page = request(server, "GET", "/")
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
        _, page = request(server, "GET", "/")
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
            _, page = request(server, "GET", "/")
            token = re.search(r"const token='([^']+)'", page)[1]
        code, _ = request(server, "POST", "/api/shutdown_bot", token)
        assert code == (403 if available else 400)
        assert not stopped.is_set()
        assert app.events == []
    finally:
        server.shutdown()
        server.server_close()
