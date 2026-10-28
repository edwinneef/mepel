import copy
import io
import json

import numpy as np
import pytest

from maplebot.map_filter import MapFilter
from maplebot.osms_import import VERIFIED_COMMIT, convert, import_osms
from maplebot.spawn_metadata import install_dataset


@pytest.fixture
def source():
    return ({"total": 4, "regions": [{"maps": [
        {"id": 10003052, "name": "Forest III", "street_name": "Road",
         "mob_positions": [{"id": 2}, {"id": 20}]},
        {"id": 10003051, "name": "Forest II", "street_name": "Road",
         "mob_positions": [{"id": 3}]},
        {"id": 10003000, "name": "Town", "street_name": "Road"},
        {"id": 900000000, "name": "", "street_name": ""},
    ]}]}, {"total": 3, "monsters": [
        {"id": 2, "name": "Snail"}, {"id": 20, "name": "Snail"},
        {"id": 3, "name": "Missing"},
    ]})


def test_bulk_coverage_empty_maps_and_missing_map_cannot_hold_previous_set(tmp_path, source,
                                                                         monkeypatch):
    data = convert(*source, VERIFIED_COMMIT, "a" * 64)
    assert data["maps"][0]["mapId"] == "010003052"
    assert "mob_positions" not in data["maps"][0]
    assert data["skippedUnnamedMaps"] == ["900000000"]
    install_dataset(tmp_path / "spawn-metadata", data)
    router = MapFilter(tmp_path / "templates", [{"id": 10, "name": "Snail"}],
                       "osms-classic", VERIFIED_COMMIT)
    try:
        assert router.match("Road Forest III") == ("Forest III", {"Snail"})
        router.taught = ("Forest III", {"Snail"})
        assert router.match("Road Forest II") == ("Forest II", None)
        assert router.coverage_error == "Missing sprite coverage: Missing"
        monkeypatch.setattr(router, "_select", lambda image: None)
        assert router.select(np.zeros((64, 310, 3)), taught_map=True) is None
        assert not router.held
        assert router.match("Road Town") == ("Town", set())
        assert router.coverage_error is None
        assert router.match("Road Forest III") == ("Forest III", {"Snail"})
        assert router.match("Road Forest IV") == (None, None)
        # Same-title ambiguity must include coverage requirements from every candidate.
        router.profiles[1]["name"] = "Forest III"
        assert router.match("Road Forest III") == ("Forest III", None)
    finally:
        router.close()


def test_download_is_pinned_atomic_dry_runnable_and_immutable(tmp_path, source, monkeypatch):
    urls = []
    def fetch(url, timeout):
        urls.append(url)
        return io.BytesIO(json.dumps(source[0 if url.endswith("maps.json") else 1]).encode())
    monkeypatch.setattr("maplebot.osms_import.urlopen", fetch)
    root = tmp_path / "store"
    entries = [{"id": 10, "name": "Snail"}]
    report = import_osms(root, entries, dry_run=True)
    assert not root.exists()
    assert report["coveredMaps"] == 2 and report["emptyMaps"] == 1
    assert report["blockedMaps"][0]["missing"] == ["Missing"]
    assert all(f"/{VERIFIED_COMMIT}/" in url for url in urls)
    assert import_osms(root, entries)["changed"]
    assert not import_osms(root, entries)["changed"]
    before = list(root.rglob("*.json"))[0].read_bytes()
    source[0]["regions"][0]["maps"][0]["name"] = "Changed"
    with pytest.raises(ValueError, match="Revision already exists"):
        import_osms(root, entries)
    assert list(root.rglob("*.json"))[0].read_bytes() == before


@pytest.mark.parametrize("change", [
    lambda m, s: m.update(total=999),
    lambda m, s: m["regions"][0]["maps"][0].update(mob_positions=[{"id": 99}]),
    lambda m, s: m["regions"][0]["maps"].append(copy.deepcopy(m["regions"][0]["maps"][0])),
    lambda m, s: s["monsters"][1].update(id=2),
    lambda m, s: s["monsters"][0].update(id=True),
])
def test_malformed_or_unknown_references_rejected(source, change):
    change(*source)
    with pytest.raises(ValueError):
        convert(*source, VERIFIED_COMMIT, "a" * 64)


def test_unpinned_revision_rejected_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr("maplebot.osms_import.urlopen", lambda *a, **kw: pytest.fail("network"))
    with pytest.raises(ValueError, match="commit SHA"):
        import_osms(tmp_path, [], "main")


def test_failed_download_never_writes_partial_dataset(tmp_path, source, monkeypatch):
    def fetch(url, timeout):
        if url.endswith("monsters.json"):
            raise OSError("offline")
        return io.BytesIO(json.dumps(source[0]).encode())
    monkeypatch.setattr("maplebot.osms_import.urlopen", fetch)
    with pytest.raises(OSError, match="offline"):
        import_osms(tmp_path / "store", [])
    assert not (tmp_path / "store").exists()
