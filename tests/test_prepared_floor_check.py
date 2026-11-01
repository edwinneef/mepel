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
