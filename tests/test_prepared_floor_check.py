import time
from copy import deepcopy

from tools.prepared_floor_check import AREA, floor_blocker


def ready():
    return {"captured_at": time.time(), "mode": "capture",
            "alarm": {"active": False}, "focused": True,
            "input_state": {"held_keys": [], "active": False, "queued": False},
            "position": {"area_id": AREA, "surface_id": "fh66"},
            "readiness": {"combat": {"ready": True}}}


def test_floor_only_preflight_refuses_wrong_surface_and_busy_input():
    assert floor_blocker(ready()) is None
    alarmed = deepcopy(ready())
    alarmed["alarm"].update({"active": True})
    assert floor_blocker(alarmed) is None  # starting acknowledges an earlier alarm
    for key, patch in [("position", {"surface_id": "rope5"}),
                       ("position", {"stale": True}),
                       ("input_state", {"held_keys": ["left"]}),
                       ("input_state", {"queued": True}),
                       ("readiness", {"combat": {"ready": False}})]:
        status = deepcopy(ready())
        status[key].update(patch)
        assert floor_blocker(status)


def test_focus_uses_guarded_command_once_and_rejects_refusal():
    import pytest

    from tools.prepared_floor_check import restore_focus

    class Api:
        def __init__(self, allowed):
            self.allowed = allowed
            self.calls = []

        def status(self):
            status = ready()
            status["focused"] = bool(self.calls) and self.allowed
            return status

        def command(self, name, payload):
            self.calls.append((name, payload))
            return {"focused": self.allowed}

    api = Api(True)
    assert restore_focus(api)["focused"]
    assert api.calls == [("focus_game", {"click_fallback": True})]
    denied = Api(False)
    with pytest.raises(RuntimeError, match="no retry"):
        restore_focus(denied)
    assert len(denied.calls) == 1


def test_focus_is_restored_even_when_cached_status_claims_focused():
    from tools.prepared_floor_check import restore_focus

    class Api:
        calls = []

        def status(self):
            return ready()

        def command(self, name, payload):
            self.calls.append(name)
            return {"focused": True}

    api = Api()
    assert restore_focus(api)["focused"]
    assert api.calls == ["focus_game"]


def test_focus_waits_through_stale_unfocused_capture_without_refocusing():
    from tools.prepared_floor_check import restore_focus

    class Api:
        calls = 0
        reads = 0

        def command(self, name, payload):
            self.calls += 1
            return {"focused": True}

        def status(self):
            self.reads += 1
            s = ready()
            s["captured_at"] = 9 if self.reads < 4 else 11
            s["focused"] = self.reads >= 4
            return s

    api = Api()
    sleeps = []
    assert restore_focus(api, wall_clock=lambda: 10, sleep=sleeps.append)["focused"]
    assert api.calls == 1
    assert len(sleeps) == 2


def test_focus_timeout_does_not_arm_or_retry_focus():
    import pytest

    from tools.prepared_floor_check import restore_focus

    class Api:
        calls = []

        def status(self):
            s = ready()
            s["captured_at"] = 9
            return s

        def command(self, name, payload):
            self.calls.append(name)
            return {"focused": True}

    api = Api()
    ticks = iter([0, 0, 3])
    with pytest.raises(RuntimeError, match="No fresh focused capture"):
        restore_focus(api, clock=lambda: next(ticks), wall_clock=lambda: 10,
                      sleep=lambda _: None)
    assert api.calls == ["focus_game"]


def test_the_start_click_acknowledges_the_previous_alarm_before_focus():
    # Batch 7 refused with "Engine no longer ready during focus handoff": batch 6's alarm
    # was still active, and the handoff treated it as new.
    from tools.prepared_floor_check import restore_focus

    class Api:
        def __init__(self):
            self.calls, self.alarm = [], True

        def status(self):
            status = ready()
            status["alarm"] = {"active": self.alarm, "incident_id": "old" if self.alarm else None}
            status["focused"] = any(name == "focus_game" for name, _ in self.calls)
            return status

        def command(self, name, payload):
            self.calls.append((name, payload))
            if name == "acknowledge":
                self.alarm = False
                return {"acknowledged": True}
            return {"focused": True}

    api = Api()
    assert restore_focus(api)["focused"]
    assert api.calls[0] == ("acknowledge", {"incident_id": "old"})
    assert api.calls[1] == ("focus_game", {"click_fallback": True})
