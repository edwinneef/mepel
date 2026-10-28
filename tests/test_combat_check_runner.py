import copy

import pytest

from tools.combat_check import run


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
