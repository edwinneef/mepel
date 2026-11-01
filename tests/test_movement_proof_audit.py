import json
from pathlib import Path

import pytest

from maplebot.profiles import validate_profile
from tools.movement_proof_audit import (
    ROOT,
    SOURCE_FILES,
    audit,
    current_context,
    object_hash,
    write_report,
)


@pytest.fixture
def evidence(tmp_path):
    areas = tmp_path / "data/areas"
    (areas / "proofs").mkdir(parents=True)
    for name in SOURCE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# fixture {name}\n")
    config = tmp_path / "config.toml"
    config.write_text('[input]\njump="space"\n')
    physics = tmp_path / "physics.json"
    physics.write_text('{"parameters": {}}')
    profile = {"schema_version": 2, "id": "a" * 32, "name": "Fixture", "revision": 1,
               "boundary": {"x": 0, "y": 0, "width": 120, "height": 80},
               "views": [{"id": "view", "name": "View", "width": 120, "height": 80,
                          "origin": {"x": 0, "y": 0}, "scale": 1, "image": "b" * 64,
                          "minimap": {"canvas": {"x": 0, "y": 0, "width": 20, "height": 20},
                                      "dot": None}}],
               "zones": [], "platforms": [], "ropes": [], "links": []}
    normalized, _ = validate_profile(profile)
    (areas / f"{profile['id']}.json").write_text(json.dumps(profile))
    proof = {"area_id": profile["id"], "map_hash": object_hash(normalized),
             "moves": {"m_floor_ledge": {"proved_at": 123.0}}}
    path = areas / "proofs" / f"{profile['id']}.json"
    path.write_text(json.dumps(proof))
    return tmp_path, areas, config, physics, path, proof


def test_legacy_provenance_stays_unknown_and_all_inputs_unchanged(evidence):
    root, areas, config, physics, path, _ = evidence
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report = audit(areas, current_context(root, config, physics))
    row = report["proof_files"][0]
    assert row["map_status"] == "match"
    assert report["summary"]["unknown"] == 1
    assert row["moves"][0]["controls"] == row["moves"][0]["physics"] == "unknown"
    assert report["native_acceptance"] is report["proofs_modified"] is False
    assert before == {p: p.read_bytes() for p in before}


@pytest.mark.parametrize("fault", [None, "source", "controls", "physics", "map"])
def test_matching_and_changed_declared_contexts(evidence, fault):
    root, areas, config, physics, path, proof = evidence
    current = current_context(root, config, physics)
    proof["moves"]["m_floor_ledge"]["provenance"] = current
    path.write_text(json.dumps(proof))
    if fault == "source":
        (root / SOURCE_FILES[0]).write_text("# changed")
    elif fault == "controls":
        config.write_text('[input]\njump="alt"\n')
    elif fault == "physics":
        physics.write_text('{"parameters": {"gravity": 2}}')
    elif fault == "map":
        area = areas / f"{proof['area_id']}.json"
        value = json.loads(area.read_text())
        value["revision"] += 1
        area.write_text(json.dumps(value))
    report = audit(areas, current_context(root, config, physics))
    row = report["proof_files"][0]
    assert row["map_status"] == ("mismatch" if fault == "map" else "match")
    assert row["moves"][0]["status"] == (
        "mismatch" if fault in {"source", "controls", "physics"} else "match")
    assert report["native_acceptance"] is False


@pytest.mark.parametrize("content", ['[1]', '{', '{}', '{"area_id":"../escape"}'])
def test_malformed_proof_is_reported_without_repair(evidence, content):
    root, areas, config, physics, path, _ = evidence
    path.write_text(content)
    report = audit(areas, current_context(root, config, physics))
    assert report["summary"]["invalid_files"] == 1
    assert path.read_text() == content


def test_missing_area_source_config_physics_and_malformed_move_stay_explicit(evidence):
    root, areas, config, physics, path, proof = evidence
    (areas / f"{proof['area_id']}.json").unlink()
    (root / SOURCE_FILES[0]).unlink()
    config.write_text("[broken")
    physics.unlink()
    proof["moves"]["bad"] = {"proved_at": float("nan")}
    proof["moves"]["m_floor_ledge"]["provenance"] = []
    path.write_text(json.dumps(proof))
    report = audit(areas, current_context(root, config, physics))
    assert report["proof_files"][0]["map_status"] == "unknown"
    assert report["summary"]["invalid"] == report["summary"]["unknown"] == 1
    assert len(report["current"]["errors"]) == 3


def test_output_is_new_and_cannot_replace_inputs_or_live_data(evidence):
    root, areas, config, physics, proof, _ = evidence
    report = audit(areas, current_context(root, config, physics))
    output = root / "artifacts/audit.json"
    args = {"root": root, "areas": areas, "config": config, "physics": physics}
    write_report(output, report, **args)
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_report(output, {}, **args)
    assert output.read_bytes() == original
    for path in (proof, physics, config, areas / "new.json", root / "src/new.json",
                 root / "data/elsewhere.json", root / "tools/new.json",
                 ROOT / "data/protected-proof-audit-test.json"):
        with pytest.raises(ValueError, match="outside saved data"):
            write_report(path, {}, **args)
    assert not (areas / "new.json").exists()


def test_custom_input_directory_is_protected(evidence):
    root, _, config, physics, _, _ = evidence
    custom = root / "custom"
    with pytest.raises(ValueError):
        write_report(custom / "proofs/new.json", {}, root=root, areas=custom,
                     config=config, physics=physics)
    assert not Path(custom).exists()
