import copy
import json

import cv2
import numpy as np
import pytest

from tools.alignment_corpus import audit, coordinate_check, digest, inventory, write_report


def anchors():
    return [{"name": str(i), "world": p, "render": [p[0] + 25, p[1] + 40],
             "uncertainty_px": 0, "withheld": i == 2}
            for i, p in enumerate(([-10, -20], [90, -20], [-10, 80]))]


def test_coordinate_check_uses_independent_withheld_anchor():
    assert coordinate_check(anchors())["translation"] == [25, 40]
    wrong = anchors()
    wrong[2]["render"][0] += 5
    with pytest.raises(ValueError, match="mismatch"):
        coordinate_check(wrong)


@pytest.mark.parametrize("fault", ["duplicate", "collinear", "not-withheld", "uncertain",
                                  "scaled", "nonfinite"])
def test_bad_coordinate_evidence_is_rejected(fault):
    points = anchors()
    if fault == "duplicate":
        points[1]["name"] = points[0]["name"]
    elif fault == "collinear":
        points[2]["world"] = [190, -20]
    elif fault == "not-withheld":
        points[2]["withheld"] = False
    elif fault == "uncertain":
        points[0]["uncertainty_px"] = 3
    elif fault == "scaled":
        for a in points:
            a["render"] = [2 * p for p in a["render"]]
    else:
        points[0]["world"][0] = float("nan")
    with pytest.raises(ValueError):
        coordinate_check(points)


@pytest.fixture
def manifest(tmp_path):
    points = anchors()
    assets = {}
    for role in ("raw", "placements", "render"):
        path = tmp_path / ("render.png" if role == "render" else f"{role}.json")
        if role == "render":
            cv2.imwrite(str(path), np.zeros((200, 200, 3), dtype=np.uint8))
        else:
            path.write_text(json.dumps({"id": 1000, "portals": [
                {"name": p["name"], "x": p["world" if role == "raw" else "render"][0],
                 "y": p["world" if role == "raw" else "render"][1]} for p in points]}))
        assets[role] = {"path": path.name, "sha256": digest(path), "build": "fixture"}
    value = {"evidence_kind": "synthetic_reference_render", "split_audit": {
        "unresolved_rows": 0, "observed_aliases": []}, "maps": [{"map_id": "000001000",
        "aliases": ["Field West of Amherst"], "split": "evaluation", "anchors": points,
        **assets}]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value))
    return path, value


def test_audit_verifies_hashes_builds_aliases_and_independent_coordinates(manifest):
    path, _ = manifest
    result = audit(path)
    assert result["admitted_maps"] == 1
    assert result["missing_reserved_maps"]
    assert result["native_acceptance"] is result["native_build_verified"] is False
    assert result["ready_for_generation"] is False


@pytest.mark.parametrize("fault", ["hash", "build", "recording", "seen", "anchor", "missing"])
def test_manifest_admission_fails_closed(manifest, fault):
    path, original = manifest
    value = copy.deepcopy(original)
    row = value["maps"][0]
    if fault == "hash":
        row["raw"]["sha256"] = "0" * 64
    elif fault == "build":
        row["render"]["build"] = "other"
    elif fault == "recording":
        value["split_audit"]["unresolved_rows"] = 1
    elif fault == "seen":
        value["split_audit"]["observed_aliases"] = ["fieldwestofamherst"]
    elif fault == "anchor":
        row["anchors"][0]["world"] = [1000, 1000]
    else:
        row["raw"] = None
    path.write_text(json.dumps(value))
    assert audit(path)["admitted_maps"] == 0


def test_inventory_does_not_inspect_renders_and_reports_unknown_recordings(tmp_path):
    clips = tmp_path / "data/recordings/clip"
    clips.mkdir(parents=True)
    (clips / "decisions.jsonl").write_text('{"catalog": {}}\n')
    result = inventory(tmp_path)
    assert result["split_audit"]["unresolved_rows"] == 1
    assert len(result["maps"]) == 6
    assert all(r["raw"] is None and r["render"] is None for r in result["maps"])


def test_reports_never_overwrite_existing_files(tmp_path):
    path = tmp_path / "report.json"
    write_report(path, {"input_sent": False})
    with pytest.raises(FileExistsError):
        write_report(path, {})
