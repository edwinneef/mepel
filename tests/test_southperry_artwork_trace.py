import copy
import json

import pytest

from tools.export_classic_assets import digest
from tools.trace_southperry_artwork import EXPECTED, summarize, validate_copies


def index():
    return {"schema": 1, "map_id": "000000060", "archives": [{"category": "Obj",
            "canvas": True, "index_text": "LastWzIndex|0",
            "path": "C:/original/Map/Obj/_Canvas/_Canvas_000.wz",
            "matching_images": ["obj_demo.img"]}]}


def trace_report():
    return {"schema": 1, "map_id": "000000060", "branches": [{}], "links": [{
        "image": "Map/Obj/obj_demo.img", "property": "house/0/0",
        "target": "Map/Obj/_Canvas/obj_demo.img/house/0/0", "target_is_copied": False}]}


def test_missing_bitmap_file_is_backed_by_observed_index_and_keeps_closure_open():
    report = trace_report()
    original = copy.deepcopy(report)
    summary = summarize(report, index())
    assert report == original
    assert list(summary["missing_bitmap_archives"]) == ["Map/Obj/_Canvas/_Canvas_000.wz"]
    assert summary["bitmap_link_closure_verified"] is False


@pytest.mark.parametrize("fault", ["map", "traversal", "category", "copied", "shards", "image"])
def test_invalid_links_or_unproven_physical_mapping_are_refused(fault):
    report, observed = trace_report(), index()
    if fault == "map":
        report["map_id"] = "000001000"
    elif fault == "traversal":
        report["links"][0]["target"] = "../Map/Obj/_Canvas/obj_demo.img/a"
    elif fault == "category":
        report["links"][0]["target"] = "Map/Map/Map0/000001000.img/a"
    elif fault == "copied":
        report["links"][0]["target_is_copied"] = True
    elif fault == "shards":
        observed["archives"][0]["index_text"] = "LastWzIndex|1"
    elif fault == "image":
        observed["archives"][0]["matching_images"] = []
    with pytest.raises(ValueError):
        summarize(report, observed)


def test_local_link_cycles_refuse_instead_of_claiming_closed():
    report = trace_report()
    report["links"] = [{"image": "Map/Obj/obj_demo.img", "property": source,
                        "target": "Map/Obj/obj_demo.img/" + target, "target_is_copied": True}
                       for source, target in (("a", "b"), ("b", "a"))]
    with pytest.raises(ValueError, match="cycle"):
        summarize(report, index())


def make_copies(tmp_path):
    root = tmp_path / "copies"
    rows = []
    for name in sorted(EXPECTED):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tiny copied fixture")
        rows.append({"relative": name, "copy": str(path), "sha256": digest(path),
                     "bytes": path.stat().st_size, "original": str(tmp_path / "original" / name)})
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(rows))
    return root, receipt, rows


@pytest.mark.parametrize("fault", ["none", "hash", "duplicate", "installed", "size"])
def test_copy_receipt_preserves_hash_and_source_boundaries(tmp_path, fault):
    root, receipt, rows = make_copies(tmp_path)
    if fault == "none":
        assert set(validate_copies(root, receipt)[1]) == EXPECTED
        return
    if fault == "hash":
        rows[0]["sha256"] = "0" * 64
    elif fault == "duplicate":
        rows[0] = rows[1]
    elif fault == "installed":
        rows[0]["original"] = rows[0]["copy"]
    elif fault == "size":
        rows[0]["bytes"] = -1
    receipt.write_text(json.dumps(rows))
    with pytest.raises(ValueError):
        validate_copies(root, receipt)
