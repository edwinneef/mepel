import copy
import io
import json
from urllib.error import HTTPError

import pytest

from maplebot.contracts import CommandGate
from tools.combat_check import Debugger, run


def ready():
    return {"session_id": "test", "mode": "capture", "focused": True,
            "readiness": {"combat": {"ready": True}},
            "attack_setup": {"profile": "classic_2h_sword"},
            "player": {"confidence": 1, "box": {"y": 10, "height": 20}},
            "monsters": [{"confidence": 1, "box": {"y": 10, "height": 20}}]}


class Api:
    def __init__(self):
        self.value = ready()
        self.calls = []
        self.fail = False

    def status(self):
        if self.fail and self.value["mode"] == "live":
            raise RuntimeError("connection lost")
        return copy.deepcopy(self.value)

    def command(self, name, status):
        self.calls.append(name)
        self.value["mode"] = "live" if name == "arm" else "capture"


class Timer:
    def __init__(self, seconds, callback):
        assert seconds == 13
        self.callback = callback

    def start(self):
        pass

    def cancel(self):
        pass


def test_one_attempt_stops_at_deadline_and_saves_evidence(tmp_path):
    api = Api()
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    result = run(api, tmp_path / "run", clock=lambda: now[0], sleep=sleep, timer_factory=Timer)
    assert api.calls == ["arm", "stop"]
    assert 13 <= now[0] < 13.11
    assert result["after"]["mode"] == "capture"
    assert (tmp_path / "run/result.json").exists()


@pytest.mark.parametrize("change", ["focus", "enemy", "tracked", "range", "alarm"])
def test_preflight_never_arms_when_blocked(tmp_path, change):
    api = Api()
    if change == "focus":
        api.value["focused"] = False
    elif change == "enemy":
        api.value["monsters"] = []
    elif change == "tracked":
        api.value["player"]["tracked"] = True
    elif change == "range":
        api.value["attack_setup"]["profile"] = "classic_bow"
    else:
        api.value["readiness"]["combat"] = {"ready": False, "reason": "Alarm"}
    with pytest.raises(RuntimeError):
        run(api, tmp_path / "run", timer_factory=Timer)
    assert api.calls == []


def test_poll_failure_still_stops_without_retry(tmp_path):
    api = Api()
    api.fail = True
    with pytest.raises(RuntimeError, match="connection lost"):
        run(api, tmp_path / "run", timer_factory=Timer)
    assert api.calls == ["arm", "stop"]
    assert (tmp_path / "run/result.json").exists()


@pytest.mark.parametrize("body", [b'{"error":"Close overlay settings before starting"}',
                                b"plain server failure", b"invalid utf8: \xff"])
def test_http_rejection_saved_and_stopped_without_retry(tmp_path, monkeypatch, body):
    api = Debugger.__new__(Debugger)
    api.base, api.token = "http://offline.invalid", "private-token"
    status = ready() | {"command_epoch": 0,
                        "frame": {"id": "test:10", "available": True, "age_ms": 0}}
    calls = []
    gate = CommandGate()

    def respond(request, timeout):
        envelope = json.loads(request.data)
        name, _, _ = gate.accept(envelope, status)
        calls.append(name)
        assert timeout == 2
        if name == "arm":
            raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(body))
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr("tools.combat_check.urlopen", respond)
    monkeypatch.setattr(api, "status", lambda: copy.deepcopy(status))
    with pytest.raises(RuntimeError, match="arm rejected \\(HTTP 400\\)"):
        run(api, tmp_path / "run", timer_factory=Timer)
    result = json.loads((tmp_path / "run/result.json").read_text())
    assert body.decode("utf-8", errors="replace") in result["error"]
    assert result["samples"] == []
    assert result["after"]["mode"] == "capture"
    assert result["stop_errors"] == []
    assert calls == ["arm", "stop"]


def test_cleanup_failures_do_not_hide_original_error(tmp_path):
    api = Api()
    count = [0]

    def status():
        count[0] += 1
        if count[0] > 1:
            raise RuntimeError("status unavailable")
        return ready()

    def command(name, status):
        api.calls.append(name)
        raise RuntimeError("arm rejected" if name == "arm" else "stop unavailable")

    api.status, api.command = status, command
    with pytest.raises(RuntimeError, match="arm rejected"):
        run(api, tmp_path / "run", timer_factory=Timer)
    result = json.loads((tmp_path / "run/result.json").read_text())
    assert result["error"] == "arm rejected"
    assert result["stop_errors"] == ["stop unavailable"]
    assert result["after_error"] == "status unavailable"
    assert api.calls == ["arm", "stop"]


def test_rejection_redacts_debug_token(monkeypatch):
    api = Debugger.__new__(Debugger)
    api.base, api.token = "http://offline.invalid", "private-token"

    def reject(request, timeout):
        raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(b"private-token"))

    monkeypatch.setattr("tools.combat_check.urlopen", reject)
    with pytest.raises(RuntimeError, match=r"\[redacted\]") as error:
        api.command("arm", {"session_id": "test", "command_epoch": 0, "frame": {"id": 10}})
    assert api.token not in str(error.value)
