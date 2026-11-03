import json
from io import BytesIO

import pytest
import test_runtime
from test_overlay_session import fixture

from maplebot.overlay_session import OverlaySession
from maplebot.runtime import REQUIRED_PROBES
from tools.navigation_check import Debugger

app = test_runtime.app

def ready(lease):
    lease.dashboard_heartbeat({"owner": "d" * 32, "panel": False})
    lease.companion_heartbeat({"owner": "w" * 32})


def batch(lease):
    lease.dashboard_batch({"session_id": lease.app.session_id,
                           "command_epoch": lease.app.command_epoch,
                           "owner": "d" * 32, "kind": "single",
                           "area": "a" * 32, "minutes": 1})
    return dict(lease.batch_token)


def test_never_connected_lease_refuses_input_but_not_stop():
    lease, _, _, _ = fixture()
    with pytest.raises(ValueError, match="disconnected"):
        lease.guard("arm")
    lease.guard("stop")


@pytest.mark.parametrize("cause", ["stop", "disconnect", "expiry", "replacement"])
def test_cancelled_pending_batch_never_returns_after_reconnection(cause):
    lease, _, now, _ = fixture()
    ready(lease)
    token = batch(lease)
    if cause == "stop":
        lease.cancel_batch()
    elif cause == "disconnect":
        lease.dashboard_disconnect({"owner": "d" * 32})
    else:
        now[0] = 3
        if cause == "expiry":
            lease.check()
        else:
            lease.dashboard_heartbeat({"owner": "e" * 32, "panel": False})
            lease.dashboard_disconnect({"owner": "e" * 32})
    ready(lease)
    assert lease.batch_pending is None
    with pytest.raises(ValueError, match="canceled"):
        lease.runner_heartbeat({"token": token})


def test_runner_death_stops_with_dashboard_and_companion_still_alive():
    lease, app, now, events = fixture()
    ready(lease)
    token = batch(lease)
    lease.runner_heartbeat({"token": token})
    now[0] = 1.5
    ready(lease)
    now[0] = 2.1
    assert "runner" in lease.block_reason()
    lease.check()
    assert app.stop_requested.is_set()
    assert events[-1] == ("INPUT_BACKEND_FAILURE", "Batch runner disconnected; bot off")
    assert lease.batch_token is None


def test_stale_runner_cannot_stop_new_batch():
    lease, _, _, events = fixture()
    ready(lease)
    old = batch(lease)
    lease.runner_cancel({"token": old})
    new = batch(lease)
    before = len(events)
    assert lease.runner_cancel({"token": old}) == {"cancelled": False}
    assert len(events) == before
    assert lease.validate_batch(new)


def test_internal_command_epoch_changes_do_not_refresh_revoked_batch():
    lease, app, _, _ = fixture()
    ready(lease)
    token = batch(lease)
    app.command_epoch = 99
    assert lease.validate_batch(token)
    lease.cancel_batch()
    app.command_epoch = 100
    with pytest.raises(ValueError):
        lease.validate_batch(token)


def test_stop_callbacks_never_run_under_lease_lock():
    lease, app, now, _ = fixture()
    original = app.safe_stop

    def stop(*args, **kwargs):
        assert not lease.lock._is_owned()
        original(*args, **kwargs)

    app.safe_stop = stop
    ready(lease)
    lease.runner_cancel({"token": batch(lease)})
    lease.dashboard_disconnect({"owner": "d" * 32})
    ready(lease)
    now[0] = 3
    lease.check()


def test_debugger_refuses_other_engine_before_batch_heartbeat(monkeypatch):
    requests = []

    def open_(url, **kwargs):
        requests.append(url)
        if url.endswith("/api/status"):
            return BytesIO(json.dumps({"session_id": "other"}).encode())
        return BytesIO(b"x" * 43)

    monkeypatch.setattr("tools.navigation_check.urlopen", open_)
    with pytest.raises(RuntimeError, match="session changed"):
        Debugger("http://127.0.0.1:8877", expected_session="original",
                 batch_token={"session_id": "original"})
    assert requests == ["http://127.0.0.1:8877/", "http://127.0.0.1:8877/api/status"]


def test_debugger_preserves_token_and_targets_explicit_endpoint(monkeypatch):
    requests = []

    def open_(url, **kwargs):
        if isinstance(url, str):
            if url.endswith("/api/status"):
                return BytesIO(json.dumps({"session_id": "s", "command_epoch": 90,
                                          "frame": {"id": "f"}}).encode())
            return BytesIO(b"x" * 43)
        requests.append((url.full_url, json.loads(url.data)))
        return BytesIO(b"{}")

    monkeypatch.setattr("tools.navigation_check.urlopen", open_)
    api = Debugger("http://127.0.0.1:8877", expected_session="s")
    api.batch_token = {"session_id": "s", "epoch": 3}
    api.command("arm")
    api.command("stop")
    assert requests[0][0] == "http://127.0.0.1:8877/api/v1/command"
    assert requests[0][1]["payload"]["_batch_token"] == api.batch_token
    assert requests[1] == ("http://127.0.0.1:8877/api/batch_cancel",
                           {"token": api.batch_token})


def test_delayed_dashboard_click_cannot_acquire_post_stop_authorization():
    lease, app, _, _ = fixture()
    ready(lease)
    click = {"session_id": app.session_id, "command_epoch": app.command_epoch,
             "owner": "d" * 32, "kind": "single", "area": "a" * 32, "minutes": 1}
    app.command_epoch += 1
    lease.cancel_batch()
    with pytest.raises(ValueError, match="stale"):
        lease.dashboard_batch(click)
    assert lease.batch_token is None


def application_batch(app, monkeypatch):
    monkeypatch.setattr(app.windows, "verify_overlay", lambda hwnd: None, raising=False)
    lease = OverlaySession(app, clock=lambda: 0)
    lease.worker = True
    app.overlay = lease
    ready(lease)
    app.probed.update(REQUIRED_PROBES)
    return lease, batch(lease)


def test_stop_during_arm_preparation_cannot_commit_old_batch(app, monkeypatch):
    lease, token = application_batch(app, monkeypatch)

    def prepare(*args, **kwargs):
        app.request("stop", {})

    monkeypatch.setattr(app, "_prepare_rotation", prepare)
    with pytest.raises(ValueError, match="canceled"):
        app._command("arm", {"_batch_token": token})
    assert app.mode == "capture" and app.stop_requested.is_set()
    assert lease.batch_token is None
    assert not app.controller.enabled
    assert not any(down for _, down in app.controller.backend.events)


def test_countdown_batch_cannot_send_after_stop_or_reconnect(app, monkeypatch):
    from maplebot.geometry import Rect
    from maplebot.perception import Detection, Observation

    lease, token = application_batch(app, monkeypatch)
    app._command("arm", {"_batch_token": token})
    assert app.mode == "pending_arm"
    app.request("stop", {})
    ready(lease)
    # Simulate an old delayed completion trying to restore its pending countdown.
    app.mode, app.pending_at = "pending_arm", 0
    app.stop_requested.clear()
    player = Detection("player", Rect(10, 20, 20, 30), 1.0)
    monkeypatch.setattr(app.detector, "detect", lambda *args, **kwargs: Observation(player, []))
    app._process(app.image, 1)
    assert not app.controller.enabled
    assert not any(down for _, down in app.controller.backend.events)
    with pytest.raises(ValueError, match="canceled"):
        app._command("arm", {"_batch_token": token})


@pytest.mark.parametrize("failure,code", [(False, "OPERATOR_STOP"),
                                         (True, "INPUT_BACKEND_FAILURE")])
def test_runner_failure_requests_alarm_but_normal_completion_is_silent(failure, code):
    lease, _, _, events = fixture()
    ready(lease)
    token = batch(lease)
    assert lease.runner_cancel({"token": token, "failure": failure}) == {"cancelled": True}
    assert events[-1][0] == code
    assert lease.batch_token is None


def test_runner_failure_raises_real_application_alarm_and_records_clip(app, monkeypatch):
    monkeypatch.setattr(app.windows, "verify_overlay", lambda hwnd: None, raising=False)
    app.overlay = OverlaySession(app)
    app.overlay.worker = True
    ready(app.overlay)
    token = batch(app.overlay)
    app.recorder.start("runner-failure")
    app.overlay.runner_cancel({"token": token, "failure": True})
    assert app.alarm.snapshot()["active"]
    assert app.stop_record.code == "INPUT_BACKEND_FAILURE"
    assert app.stop_record.clip_path
    assert not app.controller.enabled and not app.controller.held
