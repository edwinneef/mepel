import json

import pytest

from tools.farming_check import run


class Api:
    def __init__(self, *, finish=True):
        self.calls = []
        self.finish = finish
        self.running = False

    def status(self):
        return {"session_id": "s", "mode": "live" if self.running else "capture",
                "focused": True, "position": {"area_id": "island"},
                "navigation": {"map": {"nodes": []}}, "player": {"confidence": 1}}

    def command(self, name, payload=None):
        self.calls.append((name, payload))
        self.running = name == "arm" and not self.finish


def test_session_uses_no_pet_and_always_stops(tmp_path):
    api = Api()
    result = run(api, tmp_path / "run", area="island")
    assert api.calls[0][1]["farming"] == {"session_minutes": 15, "pet_recovery": False}
    assert api.calls[-1][0] == "stop"
    assert result["error"] is None
    assert json.loads((tmp_path / "run/result.json").read_text())["after"]["mode"] == "capture"


def test_timeout_stops_and_records_failure(tmp_path):
    api = Api(finish=False)
    ticks = iter([0, 911, 912])
    result = run(api, tmp_path / "run", area="island", clock=lambda: next(ticks))
    assert "deadline" in result["error"]
    assert api.calls[-1][0] == "stop"


def test_wrong_map_sends_no_commands(tmp_path):
    api = Api()
    with pytest.raises(RuntimeError, match="Wrong map"):
        run(api, tmp_path / "run", area="wrong")
    assert api.calls == []
