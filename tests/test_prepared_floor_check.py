from copy import deepcopy

from tools.prepared_floor_check import AREA, floor_blocker


def ready():
    return {"mode": "capture", "alarm": {"active": False}, "focused": True,
            "input_state": {"held_keys": [], "active": False, "queued": False},
            "position": {"area_id": AREA, "surface_id": "fh66"},
            "readiness": {"combat": {"ready": True}}}


def test_floor_only_preflight_refuses_alarm_wrong_surface_and_busy_input():
    assert floor_blocker(ready()) is None
    for key, patch in [("alarm", {"active": True}),
                       ("position", {"surface_id": "rope5"}),
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
