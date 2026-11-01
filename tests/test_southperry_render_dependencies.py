import copy
import json

import pytest

from tools.export_classic_assets import digest
from tools.southperry_render_dependencies import dependencies, inspect


def source():
    return {"map_id": "000000060", "render_sections": {
        "0": {"info": {"tS": "tile_demo"}, "tile": {
            "0": {"u": "bsc", "no": 0}, "1": {"u": "bsc", "no": 0}}, "obj": {
                "0": {"oS": "obj_demo", "l0": "house", "l1": "a", "l2": "0"}}},
        "back": {"0": {"bS": "back_demo", "no": "1", "ani": 0}}},
        "scene_entities": {"life": {"0": {"type": "n", "id": "123"}}, "reactor": {}},
        "portal_helper": {"game": {}}}


def test_reports_exact_references_without_inventing_physical_filenames():
    raw = source()
    unchanged = copy.deepcopy(raw)
    report = dependencies(raw)
    assert raw == unchanged
    assert report["placement_counts"] == {"tile": 2, "object": 1, "background": 1}
    sets = {row["image"]: row for row in report["core_scenery"]}
    assert sets["Map/Tile/tile_demo.img"]["entries"] == ["bsc/0"]
    assert len(sets["Map/Tile/tile_demo.img"]["placements"]) == 2
    assert sets["Map/Back/back_demo.img"]["entries"] == ["back/1"]
    assert report["optional_entities"][0]["image"] == "Npc/0000123.img"
    assert all(row["physical_archive"] is None for row in sets.values())
    assert not report["physical_archive_resolution_complete"]
    assert not report["native_acceptance"]


@pytest.mark.parametrize("fault", ["map", "set-escape", "entry-escape", "background", "entity"])
def test_invalid_or_out_of_scope_references_are_refused(fault):
    raw = source()
    if fault == "map":
        raw["map_id"] = "000001000"
    elif fault == "set-escape":
        raw["render_sections"]["0"]["info"]["tS"] = "../tile_outside"
    elif fault == "entry-escape":
        raw["render_sections"]["0"]["obj"]["0"]["l0"] = "outside/entry"
    elif fault == "background":
        raw["render_sections"]["back"]["0"]["ani"] = 2
    elif fault == "entity":
        raw["scene_entities"]["life"]["0"]["type"] = "unknown"
    with pytest.raises(ValueError):
        dependencies(raw)


def test_report_requires_pinned_export_and_never_overwrites(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    raw = bundle / "raw.json"
    raw.write_text(json.dumps(source()))
    manifest = {"map_id": "000000060", "outputs": {"raw.json": digest(raw)},
                "inputs": {"Map/Map/Map0/Map0_000.wz": {}}}
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    output = tmp_path / "report.json"
    report = inspect(bundle, output)
    assert not any(report["artwork_categories_present_in_copies"].values())
    with pytest.raises(ValueError, match="collision"):
        inspect(bundle, output)
    raw.write_text("changed")
    with pytest.raises(ValueError, match="hash"):
        inspect(bundle, tmp_path / "other.json")
