import json

from tools import prepared_farm_check


class Api:
    def __init__(self, surface="fh300"):
        self.calls = []
        self.surface = surface

    def status(self):
        return {"session_id": "s", "mode": "capture", "focused": True,
                "input_state": {"held_keys": []},
                "position": {"area_id": "tree", "surface_id": self.surface},
                "navigation": {"map": {"area_id": "tree", "nodes": [
                    {"id": "fh308", "kind": "platform", "excluded": False}], "edges": []},
                    "feedback": {"motion_ok": True, "surface": self.surface}}}

    def command(self, name, payload=None):
        self.calls.append((name, payload))


def test_wrong_platform_blocks_before_any_command(capsys, monkeypatch):
    monkeypatch.setattr(prepared_farm_check, "settle", lambda api, status, *a: (status, False))
    api = Api()
    code = prepared_farm_check.main(["--run", "--area", "tree", "--origin", "fh308"], api=api)
    assert code == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out == {"blocked": "Stand still on the recognized start platform fh308",
                   "input_sent": False}
    assert api.calls == []


def test_ready_platform_runs_one_bounded_learn_moves_session(capsys, monkeypatch):
    monkeypatch.setattr(prepared_farm_check, "settle", lambda api, status, *a: (status, True))
    seen = []

    def run(api, output, **kwargs):
        seen.append(kwargs)
        return {"outcome": "functional_success", "after": api.status()}

    monkeypatch.setattr(prepared_farm_check, "run", run)
    code = prepared_farm_check.main(
        ["--run", "--area", "tree", "--origin", "fh308", "--minutes", "5"], api=Api("fh308"))
    assert code == 0
    assert seen == [{"area": "tree", "session_minutes": 5, "learn_moves": True}]


def test_without_an_origin_the_batch_starts_where_the_player_stands(capsys, monkeypatch):
    monkeypatch.setattr(prepared_farm_check, "settle", lambda api, status, *a: (status, True))
    seen = []

    def run(api, output, **kwargs):
        seen.append((output.name, kwargs))
        return {"outcome": "functional_success", "after": api.status()}

    monkeypatch.setattr(prepared_farm_check, "run", run)
    assert prepared_farm_check.main(["--run", "--area", "tree"], api=Api("fh308")) == 0
    assert seen[0][0].startswith("prepared-farm-fh308-")
    assert "from fh308" in capsys.readouterr().out


def test_without_an_origin_an_unknown_spot_refuses_before_any_command(capsys):
    ticks = iter(range(100))
    api = Api("rope3")  # a rope, not a platform of the map
    assert prepared_farm_check.standing_platform(
        api, api.status(), "tree", clock=lambda: next(ticks), sleep=lambda _: None) is None
    assert prepared_farm_check.main(["--run", "--area", "tree"], api=_Quick("rope3")) == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out == {"blocked": "Stand still on a recognized platform of this map first",
                   "input_sent": False}


class _Quick(Api):
    """Status reads that age the clock quickly, so the search for a platform ends."""

    def status(self):
        import time
        time.sleep(.2)
        return super().status()


def test_single_platform_mode_farms_in_place_with_potions(capsys, monkeypatch):
    monkeypatch.setattr(prepared_farm_check, "settle", lambda api, status, *a: (status, True))
    seen = []

    def run(api, output, **kwargs):
        seen.append((output.name, kwargs))
        return {"outcome": "functional_success", "after": api.status()}

    monkeypatch.setattr(prepared_farm_check, "run", run)
    assert prepared_farm_check.main(
        ["--run", "--area", "tree", "--single", "--minutes", "15"], api=Api("fh308")) == 0
    name, kwargs = seen[0]
    assert name.startswith("prepared-single-fh308-")
    assert kwargs == {"area": "tree", "session_minutes": 15, "single_platform": True,
                      "consumables": True}
    assert "15-minute single-platform farm from fh308" in capsys.readouterr().out
