import base64
import copy
import json
import subprocess
import sys

import cv2
import numpy as np
import pytest

from tools.alignment_corpus import (
    CRITERIA,
    RESERVE,
    audit,
    coordinate_check,
    digest,
    generate,
    inventory,
    marker_projection,
    write_report,
)
from tools.evaluate_alignment_corpus import predict, score


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
        "aliases": ["The Field West of Amherst"], "split": "evaluation", "anchors": points,
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
        value["split_audit"]["observed_aliases"] = ["mapleroadthefieldwestofamherst"]
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


@pytest.mark.parametrize("world,expected,interval", [
    (17, 1, [16, 31]), (-17, -1, [-31, -16]), (0, 0, [-15, 15]),
    (-15, 0, [-15, 15]), (31, 1, [16, 31]),
])
def test_signed_projection_preserves_quantization_intervals(world, expected, interval):
    dot, bins = marker_projection([world, world], [0, 0], 4)
    assert dot == [expected, expected]
    assert bins == [interval, interval]


@pytest.fixture
def corpus_manifest(manifest):
    path, value = manifest
    template = value["maps"][0]
    mini = np.random.default_rng(0).integers(0, 255, (80, 80, 4), dtype=np.uint8)
    mini[..., 3] = 255
    encoded = base64.b64encode(cv2.imencode(".png", mini)[1]).decode()
    rows = []
    for index, (identity, name) in enumerate(RESERVE.items()):
        row = copy.deepcopy(template)
        row.update(map_id=identity, aliases=[name])
        for role in ("raw", "placements"):
            if index >= 2:
                row[role] = None
                continue
            raw = json.loads((path.parent / template[role]["path"]).read_text())
            raw["id"] = int(identity)
            if role == "raw":
                raw.update(footholds={}, ladderRopes=[], miniMap={"canvas": encoded,
                           "centerX": 100, "centerY": 100, "magnification": 2})
            target = path.parent / f"{identity}-{role}.json"
            target.write_text(json.dumps(raw))
            row[role] = {"path": target.name, "sha256": digest(target), "build": "fixture"}
        rows.append(row)
    value["maps"] = rows
    path.write_text(json.dumps(value))
    return path


def test_generation_is_deterministic_and_keeps_world_answers_out_of_predictor_inputs(
        corpus_manifest, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    report = generate(corpus_manifest, first, seed=7)
    generate(corpus_manifest, second, seed=7)
    assert report["frames"] == 16
    assert report["native_acceptance"] is report["input_sent"] is False
    assert (first / "inputs.json").read_bytes() == (second / "inputs.json").read_bytes()
    assert (first / "labels.json").read_bytes() == (second / "labels.json").read_bytes()
    inputs = json.loads((first / "inputs.json").read_text())
    labels = json.loads((first / "labels.json").read_text())
    assert all("truth_xy" not in f and "camera" not in f for f in inputs["frames"])
    assert {f["case"] for f in inputs["frames"]} >= {"blank", "occluded", "wrong-source"}
    assert any(f["observable"] for f in labels["frames"])
    for row in inputs["frames"]:
        assert digest(first / row["frame"]) == digest(second / row["frame"])
    with pytest.raises(FileExistsError):
        generate(corpus_manifest, first)


def test_missing_or_changed_assets_never_generate_a_corpus(manifest, corpus_manifest, tmp_path):
    path, _ = manifest
    value = json.loads(path.read_text())
    value["split_audit"]["unresolved_rows"] = 1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="No sealed"):
        generate(path, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


def test_prediction_process_does_not_read_labels_and_defaults_to_detected_players(
        corpus_manifest, tmp_path, monkeypatch):
    from pathlib import Path

    target = tmp_path / "prediction"
    generate(corpus_manifest, target)
    read = Path.read_text

    def forbidden_labels(path, *args, **kwargs):
        if path.name == "labels.json":
            raise AssertionError("Prediction read its answers")
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", forbidden_labels)
    result = predict(target / "inputs.json")
    assert result["track"] == "detected_player"
    assert all(r["predicted_xy"] is None for r in result["rows"])
    assert all(r["precision_verified"] is False for r in result["rows"])
    assert result["input_sent"] is result["native_acceptance"] is False
    oracle = predict(target / "inputs.json", track="oracle_player_geometry")
    assert oracle["track"] != result["track"]


@pytest.fixture
def score_files(tmp_path):
    common = {"evidence_kind": "synthetic_reference_render"}
    labels = {**common, "frames": [{"id": f"{key}-{i}", "sha256": str(i) * 64,
        "truth_xy": [100, 200], "observable": i < 5, "source_pair_verified": True,
        "method": "constructed_drawing_coordinates", "label_uncertainty_px": 1}
        for key in ("a", "b") for i in range(6)]}
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(labels))
    inputs = {**common, "maps": ["a", "b"], "criteria": dict(CRITERIA),
        "labels_sha256": digest(labels_path), "frames": [
            {"id": r["id"], "sha256": r["sha256"], "map_id": r["id"].split("-")[0],
             "sequence": i % 6} for i, r in enumerate(labels["frames"])]}
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps(inputs))
    predictions = {**common, "inputs_sha256": digest(inputs_path),
        "labels_sha256": digest(labels_path), "track": "oracle_player_geometry",
        "implementation_sha256": {"toy_model": "sealed"}, "rows": [
            {**r, "analysis_ms": 1, "state": "uncertain",
             "reported_interval_xy": [[100, 102], [200, 202]],
             "predicted_xy": [101, 201] if r["sequence"] < 5 else None}
            for r in inputs["frames"]]}
    predictions_path = tmp_path / "predictions.json"
    predictions_path.write_text(json.dumps(predictions))
    return inputs_path, predictions_path, labels_path


def test_constructed_scores_never_grant_native_precision_or_acceptance(score_files):
    report = score(*score_files)
    assert report["assessment"]["passed"]
    assert report["track"] == "oracle_player_geometry"
    assert report["precision_verified"] is report["native_acceptance"] is False
    assert all(r["coverage"] == 1 and r["false_ready"] == 0
               for r in report["assessment"]["maps"])
    assert all(r["p95_interval_error_px"] == 0 for r in report["assessment"]["maps"])


@pytest.mark.parametrize("fault", ["refuse-all", "wrong", "missing-map", "false-ready"])
def test_empty_wrong_or_unobservable_synthetic_predictions_cannot_pass(score_files, fault):
    inputs, predictions, labels = score_files
    value = json.loads(predictions.read_text())
    for row in value["rows"]:
        if fault == "refuse-all" or (fault == "missing-map" and row["map_id"] == "b"):
            row["predicted_xy"] = None
        elif fault == "wrong" or fault == "false-ready":
            row["predicted_xy"] = [900, 900] if fault == "wrong" else [100, 200]
    predictions.write_text(json.dumps(value))
    assert not score(inputs, predictions, labels)["assessment"]["passed"]


@pytest.mark.parametrize("fault", ["labels", "inputs", "duplicate", "native-method", "interval"])
def test_changed_or_misclassified_evaluation_evidence_is_rejected(score_files, fault):
    inputs, predictions, labels = score_files
    if fault == "labels":
        labels.write_text(labels.read_text() + " ")
    elif fault == "inputs":
        inputs.write_text(inputs.read_text() + " ")
    elif fault == "duplicate":
        value = json.loads(predictions.read_text())
        value["rows"].append(value["rows"][0])
        predictions.write_text(json.dumps(value))
    elif fault == "interval":
        value = json.loads(predictions.read_text())
        value["rows"][0]["reported_interval_xy"] = [[500, 100], [2, 1]]
        predictions.write_text(json.dumps(value))
    else:
        value = json.loads(labels.read_text())
        value["frames"][0]["method"] = "independent_world_landmarks_and_feet"
        labels.write_text(json.dumps(value))
        source = json.loads(inputs.read_text())
        source["labels_sha256"] = digest(labels)
        inputs.write_text(json.dumps(source))
        results = json.loads(predictions.read_text())
        results.update(inputs_sha256=digest(inputs), labels_sha256=digest(labels))
        predictions.write_text(json.dumps(results))
    with pytest.raises(ValueError):
        score(inputs, predictions, labels)


def test_synthetic_cli_seals_predictions_before_separate_scoring(corpus_manifest, tmp_path):
    target = tmp_path / "cli"
    generate(corpus_manifest, target)
    predictions, report = target / "predictions.json", target / "report.json"
    command = [sys.executable, "-m", "tools.evaluate_unseen_positioning", "synthetic"]
    subprocess.run([*command, "predict", "--inputs", str(target / "inputs.json"),
                    "--output", str(predictions)], check=True, capture_output=True, timeout=30)
    subprocess.run([*command, "score", "--inputs", str(target / "inputs.json"),
                    "--predictions", str(predictions), "--labels", str(target / "labels.json"),
                    "--output", str(report)], check=True, capture_output=True, timeout=30)
    result = json.loads(report.read_text())
    assert result["assessment"]["passed"] is False  # All-refused and missing maps stay failures.
    assert result["input_sent"] is result["native_acceptance"] is False
