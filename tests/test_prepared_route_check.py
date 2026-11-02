from copy import deepcopy

import pytest

import tools.prepared_route_check as check

AREA = "a" * 32


def ready():
    return {"capture_only": False, "mode": "capture", "alarm": {"active": False},
            "focused": True, "input_state": {"held_keys": [], "active": False, "queued": False},
            "position": {"area_id": AREA, "surface_id": "fh315"},
            "navigation": {"feedback": {"motion_ok": True, "surface": "fh315"},
                           "map": {"area_id": AREA, "nodes": [
                {"id": "fh315", "excluded": False}, {"id": "fh308", "excluded": False},
                {"id": "fh68", "excluded": True}]}}}


def test_route_preflight_refuses_every_unready_state():
    assert check.route_blocker(ready(), AREA, "fh315", "fh308") is None
    for key, patch in [("alarm", {"active": True}), ("input_state", {"held_keys": ["left"]}),
                       ("input_state", {"queued": True}), ("position", {"surface_id": "fh308"}),
                       ("position", {"stale": True}), ("position", {"held": True}),
                       ("position", {"area_id": "b" * 32})]:
        status = deepcopy(ready())
        status[key].update(patch)
        assert check.route_blocker(status, AREA, "fh315", "fh308"), (key, patch)
    for key, value in [("capture_only", True), ("mode", "live"), ("focused", False)]:
        status = {**ready(), key: value}
        assert check.route_blocker(status, AREA, "fh315", "fh308"), key
    for feedback in ({"motion_ok": False, "surface": "fh315"},
                     {"motion_ok": True, "surface": None}):
        status = deepcopy(ready())
        status["navigation"]["feedback"] = feedback
        assert "agree" in check.route_blocker(status, AREA, "fh315", "fh308")
    assert "not loaded" in check.route_blocker(ready(), AREA, "fh315", "fh68")
    assert "not loaded" in check.route_blocker(ready(), AREA, "fh315", "fh999")


class Api:
    def __init__(self, status):
        self.value = status

    def status(self):
        return self.value


def test_settle_waits_until_recognition_holds_steady():
    found = ready()
    lost = {**found, "position": {"area_id": AREA, "surface_id": None}}
    # Found, a dropout, then found for good: steady only counts the unbroken stretch.
    statuses = iter([lost, found, lost, found, found, found, found])
    api = type("Api", (), {"status": lambda self: next(statuses)})()
    now = iter(range(100))
    status, steady = check.settle(api, lost, AREA, "fh315", seconds=8, steady=2,
                                  clock=lambda: next(now), sleep=lambda s: None)
    assert status is found and steady
    now = iter(range(100))
    flicker = iter([found, lost] * 10)
    api = type("Api", (), {"status": lambda self: next(flicker)})()
    assert check.settle(api, lost, AREA, "fh315", seconds=8, steady=2,
                        clock=lambda: next(now), sleep=lambda s: None)[1] is False


def test_blocked_route_sends_nothing(monkeypatch, capsys):
    status = {**ready(), "focused": False}
    monkeypatch.setattr(check, "Debugger", lambda: Api(status))
    monkeypatch.setattr(check, "run", lambda *a, **k: pytest.fail("route must not start"))
    assert check.main(["--run", "--area", AREA, "--origin", "fh315", "--target", "fh308"]) == 1
    assert '"input_sent": false' in capsys.readouterr().out


def test_failed_route_returns_control_and_sounds_the_alarm_once(monkeypatch, capsys):
    api = Api(ready())
    monkeypatch.setattr(check, "Debugger", lambda: api)
    routes = []

    def run(api_, output, *, limit, chosen):
        routes.append((limit, chosen))
        return {"failure": "Edge deadline exhausted", "arrived": 0, "proven_after": 0}

    played = []
    monkeypatch.setattr(check, "run", run)
    import winsound
    monkeypatch.setattr(winsound, "PlaySound", lambda *a: played.append(a))
    assert check.main(["--run", "--area", AREA, "--origin", "fh315", "--target", "fh308"]) == 1
    assert routes == [(1, ["fh308"])] and len(played) == 1
    assert "no retry" in capsys.readouterr().out
