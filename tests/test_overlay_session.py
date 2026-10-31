import threading
from types import SimpleNamespace

import pytest

from maplebot.overlay_session import OverlaySession


def fixture():
    now = [0.0]
    events = []
    app = SimpleNamespace(stop_lock=threading.RLock(), active_probe=None,
                          stop_requested=threading.Event(), closed=threading.Event())

    def stop(code, message, *, preserve_completed_probe=False):
        events.append((code, message))
        if not (preserve_completed_probe and app.active_probe
                and app.active_probe.phase == "awaiting_confirmation"):
            app.active_probe = None

    app.safe_stop = stop
    lease = OverlaySession(app, clock=lambda: now[0])
    lease.worker = True  # Exercise expiry deterministically, without a wall-clock thread.
    return lease, app, now, events


def test_open_panel_allows_starts_but_expired_lease_refuses_every_gameplay_start():
    lease, _, now, events = fixture()
    lease.heartbeat({"owner": "a" * 32, "panel": True})
    assert len(events) == 1  # Opening settings still stops running work.
    for name in ("arm", "probe", "nav_go", "nav_start", "autopotter_live", "dry_run"):
        lease.guard(name)
    lease.heartbeat({"owner": "a" * 32, "panel": False})
    lease.guard("arm")
    assert len(events) == 1  # Closing settings never starts or resumes work.
    now[0] = 3
    for name in ("arm", "probe", "nav_go", "nav_start", "autopotter_live", "dry_run"):
        with pytest.raises(ValueError, match="disconnected"):
            lease.guard(name)
    lease.guard("stop")
    lease.guard("confirm_probe")
    lease.check()
    lease.check()
    assert len(events) == 2


def test_settings_retains_only_a_completed_manual_probe_for_confirmation():
    lease, app, _, _ = fixture()
    complete = SimpleNamespace(phase="awaiting_confirmation", id=7, generation=2)
    app.active_probe = complete
    lease.heartbeat({"owner": "a" * 32, "panel": True})
    assert app.active_probe is complete
    assert app.stop_requested.is_set()
    lease.heartbeat({"owner": "a" * 32, "panel": False})
    app.active_probe = SimpleNamespace(phase="awaiting_effect")
    lease.heartbeat({"owner": "a" * 32, "panel": True})
    assert app.active_probe is None


def test_another_overlay_cannot_take_over_live_owner():
    lease, _, _, _ = fixture()
    lease.heartbeat({"owner": "a" * 32, "panel": False})
    with pytest.raises(ValueError, match="Another overlay"):
        lease.heartbeat({"owner": "b" * 32, "panel": False})


def test_reconnection_stops_input_instead_of_resuming():
    lease, _, now, events = fixture()
    lease.heartbeat({"owner": "a" * 32, "panel": False})
    now[0] = 3
    lease.check()
    lease.heartbeat({"owner": "a" * 32, "panel": False})
    assert len(events) == 3

def test_close_request_does_not_clear_gate_until_owner_acknowledges():
    lease, _, now, _ = fixture()
    lease.heartbeat({"owner": "a" * 32, "panel": True})
    assert lease.request_close() == {"requested": True}
    assert lease.heartbeat({"owner": "a" * 32, "panel": True})["close_requested"]
    assert not lease.heartbeat({"owner": "a" * 32, "panel": False})["close_requested"]
    assert lease.block_reason() is None
    now[0] = 3
    with pytest.raises(ValueError, match="disconnected"):
        lease.request_close()


def test_dashboard_uses_shared_gates_without_native_window_verification():
    lease, app, now, events = fixture()

    def refuse_native(hwnd):
        raise ValueError("Native window verification required")

    app.windows = SimpleNamespace(verify_overlay=refuse_native)
    lease.dashboard_heartbeat({"owner": "a" * 32, "panel": True})
    assert app.stop_requested.is_set()
    for name in ("arm", "probe", "nav_go", "nav_start", "nav_edge", "autopotter_live", "dry_run"):
        lease.guard(name)
    lease.guard("stop")
    lease.dashboard_heartbeat({"owner": "a" * 32, "panel": False})
    lease.guard("arm")
    assert len(events) == 1  # Acknowledging panel closure does not restart input.
    with pytest.raises(ValueError, match="Native window verification"):
        lease.heartbeat({"owner": "a" * 32, "panel": False, "surface": "dashboard"})
    now[0] = 2
    with pytest.raises(ValueError, match="Dashboard disconnected"):
        lease.guard("arm")
    lease.check()
    lease.check()
    assert len(events) == 2 and events[-1][1] == "Dashboard disconnected; bot off"


@pytest.mark.parametrize("first", ["overlay", "dashboard"])
def test_native_and_dashboard_cannot_share_or_take_over_live_lease(first):
    lease, _, now, events = fixture()
    methods = {"overlay": lease.heartbeat, "dashboard": lease.dashboard_heartbeat}
    other = "dashboard" if first == "overlay" else "overlay"
    methods[first]({"owner": "a" * 32, "panel": False})
    for owner in ("a" * 32, "b" * 32):
        with pytest.raises(ValueError, match="Another overlay"):
            methods[other]({"owner": owner, "panel": False})
    now[0] = 2
    # Even before the watchdog gets a turn, an expired lease reconnects stopped.
    methods[other]({"owner": "a" * 32, "panel": False})
    assert lease.surface == other and len(events) == 2


def test_dashboard_reconnection_after_deadline_stops_even_before_watchdog_checks():
    lease, _, now, events = fixture()
    lease.dashboard_heartbeat({"owner": "a" * 32, "panel": False})
    now[0] = 2
    lease.dashboard_heartbeat({"owner": "a" * 32, "panel": False})
    assert len(events) == 2


def test_dashboard_disconnect_stops_immediately_and_cannot_stop_replacement():
    lease, app, _, events = fixture()
    lease.dashboard_heartbeat({"owner": "a" * 32, "panel": False})
    assert lease.dashboard_disconnect({"owner": "b" * 32}) == {"disconnected": False}
    assert len(events) == 1
    assert lease.dashboard_disconnect({"owner": "a" * 32}) == {"disconnected": True}
    assert app.stop_requested.is_set() and len(events) == 2
    with pytest.raises(ValueError, match="Dashboard disconnected"):
        lease.guard("arm")
    lease.check()
    assert lease.dashboard_disconnect({"owner": "a" * 32}) == {"disconnected": False}
    assert len(events) == 2
    lease.dashboard_heartbeat({"owner": "b" * 32, "panel": False})
    assert len(events) == 3
    assert lease.dashboard_disconnect({"owner": "a" * 32}) == {"disconnected": False}
    lease.guard("arm")
    assert len(events) == 3


def test_dashboard_disconnect_cannot_expire_native_owner_with_same_id():
    lease, _, _, events = fixture()
    lease.heartbeat({"owner": "a" * 32, "panel": False})
    assert lease.dashboard_disconnect({"owner": "a" * 32}) == {"disconnected": False}
    lease.guard("arm")
    assert len(events) == 1
