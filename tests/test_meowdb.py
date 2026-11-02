import copy
import json
from pathlib import Path

import pytest

from maplebot.meowdb import load_source, normalize
from maplebot.public_map import chains, layout

FIXTURE = Path(__file__).parent / "fixtures" / "meowdb-42.json"


def bundle():
    return json.loads(FIXTURE.read_text("utf-8"))


def test_classic_export_preserves_geometry_and_does_not_bridge_steps():
    source, digest = load_source(FIXTURE, 42)
    assert len(digest) == 64
    assert len(source["footholds"]) == 196
    assert len(source["ladderRopes"]) == 10
    assert sum(r["isLadder"] for r in source["ladderRopes"]) == 5
    runs = chains(source)
    assert len(runs) == 19
    assert all(all(a["x"] < b["x"] for a, b in zip(r["points"], r["points"][1:], strict=False))
               for r in runs)
    result = layout(source, {"x": (1, 0), "y": (1, 0)}, (16, 16))
    assert len(result["zones"]) == 2
    assert result["ropes"][0]["name"].startswith("Ladder")


def test_branching_and_gapped_endpoints_stay_separate():
    data = bundle()
    data["terrain"]["fh"] = [[0, 0, 10, 0], [10, 0, 20, 0],
                              [10, 0, 20, 5], [21, 0, 30, 0]]
    assert len(chains(normalize(data))) == 4


@pytest.mark.parametrize("change", [
    {"version": 3}, {"ct": [[1, 2]]}, {"nd": [1]},
    {"fh": [[0, 0, float("nan"), 0]]}, {"lr": [[1, 0, 20, 2]]},
    {"vr": [-400, -1045, 2909, 585]},
])
def test_unknown_or_invalid_geometry_is_rejected(change):
    data = bundle()
    data["terrain"].update(change)
    with pytest.raises(ValueError):
        normalize(data)


def test_wrong_map_id_is_rejected():
    with pytest.raises(ValueError, match="map ID differs"):
        load_source(FIXTURE, 40002)


def test_legacy_profile_provenance_does_not_change_its_fingerprint():
    from maplebot.profiles import public_map_record

    legacy = {"id": 7, "sha256": "c" * 64, "world": {"x": [1, 0], "y": [1, 0]}}
    assert public_map_record(legacy) == legacy


def test_explicit_import_uses_saved_calibration_without_network(tmp_path, monkeypatch):
    from test_map_import import store

    from maplebot.map_import import import_map

    fake, public = store(tmp_path)
    data = bundle()
    data["miniMap"] = json.loads(public)["miniMap"]
    data["terrain"]["vr"] = [0, 0, 960, 640]
    export = tmp_path / "export.json"
    export.write_text(json.dumps(data))
    original = copy.deepcopy(fake.profile)
    result = import_map(fake, "Test", tmp_path / "missing", meowdb_source=export,
                        dry_run=True, fetch=lambda _: pytest.fail("Network called"))
    assert result["provider"] == "meowdb-classic"
    assert fake.saved is None and fake.profile == original
    assert not (tmp_path / "public").exists()
    import_map(fake, "Test", tmp_path / "missing", meowdb_source=export)
    fake.profile = fake.saved
    from maplebot.live_position import LivePosition

    # This import fixture has no game-window chrome; reader detection is tested
    # separately. Check that live tracking receives this provider's cached pixels.
    images = []
    monkeypatch.setattr("maplebot.live_position.AreaMinimap",
                        lambda reference, terrain: images.append(terrain))
    tracker = LivePosition(fake, fake.profile["id"])
    assert tracker.profile["public_map"]["provider"] == "meowdb-classic"
    assert images[0].shape == (40, 60, 4)
    tracker.close()


def test_meowdb_tracking_cache_is_digest_bound_and_separate(tmp_path):
    from maplebot.meowdb import cache_export, cached_source

    _, digest = load_source(FIXTURE)
    public = {"id": 42, "sha256": digest}
    with pytest.raises(ValueError, match="Cache the MeowDB"):
        cached_source(tmp_path, public)
    cache_export(tmp_path, FIXTURE, digest)
    assert cached_source(tmp_path, public)[1] == digest
    assert not (tmp_path / "public/42.json").exists()
    path = tmp_path / "public/meowdb-classic" / f"{digest}.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="changed"):
        cached_source(tmp_path, public)


def test_classic_routes_replay_at_three_fps():
    from tools.navigation_replay import replay

    source = normalize(bundle())
    profile = {"id": "a" * 32, "revision": 1, "links": [], "public_map": {"id": 42},
               **layout(source, {"x": (1, 0), "y": (1, 0)}, (16, 16))}
    result = replay(profile, fps=3)
    assert result["edges"] and result["compositions"]
    assert all(row["stage"] == "arrived" for row in result["edges"] + result["compositions"])
