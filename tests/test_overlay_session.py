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
    for name in ("arm", "probe", "nav_go", "nav_start", "nav_walk", "autopotter_live", "dry_run"):
        lease.guard(name)
    lease.heartbeat({"owner": "a" * 32, "panel": False})
    lease.guard("arm")
    assert len(events) == 1  # Closing settings never starts or resumes work.
    now[0] = 3
    for name in ("arm", "probe", "nav_go", "nav_start", "nav_walk", "autopotter_live", "dry_run"):
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
        held = "Another dashboard tab holds controls" if first == "dashboard" else "Another overlay"
        with pytest.raises(ValueError, match=held):
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


def test_widget_companion_does_not_claim_or_renew_dashboard_control():
    lease, _, now, events = fixture()
    lease.dashboard_heartbeat({"owner": "d" * 32, "panel": False})
    result = lease.companion_heartbeat({"owner": "w" * 32})
    assert result["controller_ready"] is True
    assert lease.owner == "d" * 32 and lease.surface == "dashboard"
    deadline = lease.deadline
    now[0] = 1
    lease.companion_heartbeat({"owner": "w" * 32})
    assert lease.deadline == deadline and len(events) == 1
    now[0] = 2.1
    assert lease.companion_heartbeat({"owner": "w" * 32})["controller_ready"] is False
    with pytest.raises(ValueError, match="Dashboard disconnected"):
        lease.guard("arm")
    lease.check()
    assert len(events) == 2


def test_overlay_loss_stops_once_without_disconnecting_dashboard():
    lease, _, now, events = fixture()
    lease.companion_heartbeat({"owner": "w" * 32})
    with pytest.raises(ValueError, match="dashboard"):
        lease.guard("arm")
    lease.dashboard_heartbeat({"owner": "d" * 32, "panel": False})
    now[0] = 1.5
    lease.dashboard_heartbeat({"owner": "d" * 32, "panel": False})
    now[0] = 2.1
    lease.check()
    assert len(events) == 2 and "In-game overlay disconnected" in events[-1][1]
    assert lease.owner == "d" * 32 and not lease.expired
    lease.check()
    assert len(events) == 2
    lease.guard("stop")


def _ready_dashboard_with_widget(lease):
    lease.dashboard_heartbeat({"owner": "d" * 32, "panel": False})
    lease.companion_heartbeat({"owner": "w" * 32})


def test_dashboard_batch_is_queued_once_for_the_widget_host_and_never_starts_input():
    lease, app, now, events = fixture()
    _ready_dashboard_with_widget(lease)
    request = {"owner": "d" * 32, "kind": "learn", "area": "a" * 32, "minutes": 1,
               "circuit": {"id": "lower-loop", "revision": 2}}
    assert lease.dashboard_batch(request) == {"queued": True, "id": 1}
    with pytest.raises(ValueError, match="already running"):
        lease.dashboard_batch(request)
    pending = lease.companion_heartbeat({"owner": "w" * 32})["batch_request"]
    assert pending == {"kind": "learn", "area": "a" * 32, "minutes": 1,
                       "circuit": {"id": "lower-loop", "revision": 2}, "id": 1}
    # The host acknowledges and reports progress; the request is consumed exactly once.
    progress = {"running": True, "kind": "learn", "line": "Starting"}
    result = lease.companion_heartbeat({"owner": "w" * 32, "batch": progress,
                                        "batch_ack": {"id": 1, "started": True}})
    assert result["batch_request"] is None
    status = lease.dashboard_heartbeat({"owner": "d" * 32, "panel": False})["batch"]
    assert status == {"running": True, "kind": "learn", "line": "Starting", "pending": False}
    with pytest.raises(ValueError, match="already running"):
        lease.dashboard_batch({**request, "kind": "single"})
    done = {"running": False, "kind": "learn", "code": 0, "output": "x" * 5000}
    lease.companion_heartbeat({"owner": "w" * 32, "batch": done})
    assert len(lease.batch_status()["output"]) == 4000
    single = {**request, "kind": "single", "circuit": None}
    assert lease.dashboard_batch(single) == {"queued": True, "id": 2}
    assert len(events) == 1  # only the pause from opening the lease; queueing stops nothing


def test_dashboard_batch_refusals():
    lease, _, now, events = fixture()
    good = {"owner": "d" * 32, "kind": "single", "area": "a" * 32, "minutes": 15}
    with pytest.raises(ValueError, match="disconnected"):
        lease.dashboard_batch(good)  # no dashboard lease
    lease.dashboard_heartbeat({"owner": "d" * 32, "panel": False})
    with pytest.raises(ValueError, match="in-game overlay"):
        lease.dashboard_batch(good)  # no widget host to run it
    lease.companion_heartbeat({"owner": "w" * 32})
    with pytest.raises(ValueError, match="disconnected"):
        lease.dashboard_batch({**good, "owner": "x" * 32})  # not the lease owner
    for bad, message in [({"minutes": 7}, "1 or 15"), ({"area": "../x"}, "Invalid"),
                         ({"kind": "jump"}, "Invalid"), ({"kind": "learn"}, "saved loop"),
                         ({"kind": "learn", "circuit": {"id": "../x", "revision": 2}},
                          "saved loop")]:
        with pytest.raises(ValueError, match=message):
            lease.dashboard_batch({**good, **bad})
    assert lease.batch_pending is None


def test_widget_refusal_of_a_dashboard_batch_is_reported_and_clears_the_request():
    lease, _, now, events = fixture()
    _ready_dashboard_with_widget(lease)
    lease.dashboard_batch({"owner": "d" * 32, "kind": "single", "area": "a" * 32, "minutes": 1})
    refused = {"id": 1, "started": False, "reason": "Widget renderer is not fresh"}
    lease.companion_heartbeat({"owner": "w" * 32, "batch_ack": refused})
    assert lease.batch_pending is None
    assert "Widget renderer is not fresh" in lease.batch_status()["output"]
