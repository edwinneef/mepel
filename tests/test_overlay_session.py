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


def test_panel_and_expired_lease_refuse_every_gameplay_start():
    lease, _, now, events = fixture()
    lease.heartbeat({"owner": "a" * 32, "panel": True})
    for name in ("arm", "probe", "nav_go", "nav_start", "autopotter_live", "dry_run"):
        with pytest.raises(ValueError, match="Close overlay"):
            lease.guard(name)
    lease.guard("stop")
    lease.guard("confirm_probe")
    lease.heartbeat({"owner": "a" * 32, "panel": False})
    lease.guard("arm")
    assert len(events) == 1  # Closing settings never starts or resumes work.
    now[0] = 3
    with pytest.raises(ValueError, match="disconnected"):
        lease.guard("arm")
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
