import copy
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation
from tools.occlusion_evaluation import digest, evaluate, recovery_delays, run, score, validate


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "metadata.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config.toml").write_text("[perception]\nconfidence = 0.9\n", encoding="utf-8")
    (tmp_path / "source.py").write_text("# frozen implementation\n", encoding="utf-8")
    cv2.imwrite(str(tmp_path / "frame.png"), np.zeros((40, 40, 3), np.uint8))
    manifest = {
        "version": 1, "config_path": "config.toml",
        "config_sha256": digest(tmp_path / "config.toml"),
        "templates_path": "templates",
        "templates_sha256": {"metadata.json": digest(tmp_path / "templates/metadata.json")},
        "source_sha256": {"source.py": digest(tmp_path / "source.py")},
        "identities": {"Alice": ["nametag:own-player"]},
        "sequences": [{"id": "bridge", "split": "held_out", "kind": "real",
                       "complete_contiguous": False, "frames": [{
                           "path": "frame.png", "sha256": digest(tmp_path / "frame.png"),
                           "at": 1.0, "identity": "Alice", "visibility": "visible",
                           "box": [10, 10, 10, 20], "tolerance_px": 3,
                           "provenance": "independent-visual"}]}]}
    return manifest, tmp_path


def player(*, template="nametag:own-player", identity=None, tracked=False, box=None):
    return {"template": template, "identity": identity, "tracked": tracked,
            "box": box or [10, 10, 10, 20], "confidence": .99}


def test_validate_protects_inputs_and_accepts_partial_identity_without_invented_feet(corpus):
    manifest, root = corpus
    frame = manifest["sequences"][0]["frames"][0]
    frame.update(visibility="partial", box=None)
    protected = validate(manifest, root)
    assert root / "config.toml" in protected
    result = score(frame, player(), .9, manifest["identities"])
    assert result["identity_evaluable"]
    assert not result["position_evaluable"]
    assert result["position_error_px"] is None
    assert result["outcome"] == "correct_fresh_identity"


@pytest.mark.parametrize("change", [
    lambda m: m.update(version=2),
    lambda m: m.update(config_path="../outside.toml"),
    lambda m: m.update(config_sha256="0" * 64),
    lambda m: m.update(templates_sha256={}),
    lambda m: m.update(source_sha256={}),
    lambda m: m.update(identities={"Alice": ["sprite:own-player"]}),
    lambda m: m.update(monsters="false"),
    lambda m: m["sequences"][0].update(split="train"),
    lambda m: m["sequences"][0]["frames"][0].update(sha256="0" * 64),
    lambda m: m["sequences"][0]["frames"][0].update(at=float("nan")),
    lambda m: m["sequences"][0]["frames"][0].update(provenance="interpolated"),
    lambda m: m["sequences"][0]["frames"][0].update(identity="unmapped"),
    lambda m: m["sequences"][0]["frames"][0].update(visibility="hidden"),
    lambda m: m["sequences"][0]["frames"][0].update(box=[1, 2, -3, 4]),
    lambda m: m["sequences"][0]["frames"][0].update(tolerance_px=float("inf")),
])
def test_invalid_frozen_evidence_rejected_before_detection(corpus, change):
    manifest, root = corpus
    change(manifest)
    with pytest.raises(ValueError):
        validate(manifest, root)


def test_timestamp_reversal_and_cross_split_duplicate_are_rejected(corpus):
    manifest, root = corpus
    sequence = manifest["sequences"][0]
    sequence["frames"].append(copy.deepcopy(sequence["frames"][0]))
    with pytest.raises(ValueError, match="strictly increase"):
        validate(manifest, root)
    sequence["frames"].pop()
    other = copy.deepcopy(sequence)
    other.update(id="different-id", split="development")
    manifest["sequences"].append(other)
    with pytest.raises(ValueError, match="leaks across splits"):
        validate(manifest, root)


def test_synthetic_labels_are_explicitly_separate(corpus):
    manifest, root = corpus
    sequence = manifest["sequences"][0]
    sequence["kind"] = "synthetic"
    with pytest.raises(ValueError, match="interpolated"):
        validate(manifest, root)
    sequence["frames"][0]["provenance"] = "synthetic-transform"
    validate(manifest, root)


def test_spatial_match_does_not_prove_identity_and_hidden_location_is_unscored(corpus):
    manifest, _ = corpus
    frame = manifest["sequences"][0]["frames"][0]
    aliases = manifest["identities"]
    match = score(frame, player(template="own-player-sprite"), .9, aliases)
    assert match["within_tolerance"]
    assert match["identity_match"] is None
    assert match["outcome"] == "unsupported_fresh_identity"
    wrong = score(frame, player(box=[100, 10, 10, 20]), .9, aliases)
    assert wrong["outcome"] == "wrong_fresh"
    frame.update(visibility="hidden", box=None)
    hidden = score(frame, player(), .9, aliases)
    assert hidden["outcome"] == "unsupported_fresh"
    assert hidden["position_error_px"] is None
    assert not hidden["identity_evaluable"]
    assert score(frame, player(tracked=True), .9, aliases)["outcome"] == "abstained"


def test_known_different_identity_is_wrong_not_merely_unscored(corpus):
    manifest, _ = corpus
    frame = manifest["sequences"][0]["frames"][0]
    aliases = {**manifest["identities"], "Bob": ["nametag:stranger"]}
    result = score(frame, player(template="nametag:stranger"), .9, aliases)
    assert result["identity_match"] is False
    assert result["outcome"] == "wrong_fresh"


class FakeDetector:
    def __init__(self, directory, config):
        self.config = config
        self.calls = 0
        self.pool = SimpleNamespace(shutdown=lambda **_: None)

    def detect(self, image, now, *, monsters):
        assert not monsters
        self.calls += 1
        return Observation(Detection("player", Rect(10, 10, 10, 20), .99,
                                     "nametag:own-player"), [])


def test_sequences_reset_detector_semantics_are_stable_and_timing_separate(corpus):
    manifest, root = corpus
    second = copy.deepcopy(manifest["sequences"][0])
    second["id"] = "another-session"
    manifest["sequences"].append(second)
    made = []

    def factory(directory, config):
        detector = FakeDetector(directory, config)
        made.append(detector)
        return detector

    first = evaluate(manifest, root, detector_factory=factory)
    again = evaluate(manifest, root, detector_factory=factory)
    assert first["semantic"] == again["semantic"]
    assert [d.calls for d in made] == [1, 1, 1, 1]
    assert first["semantic"]["counts"]["correct_fresh_identity"] == 2
    assert first["semantic"]["counts"]["identity_evaluable"] == 2
    assert all(s["sampled_recovery"] is None for s in first["semantic"]["sequences"])
    assert not first["input_sent"] and not first["capture_started"]
    assert "detect_ms" in first["timing"][0]["frames"][0]
    assert "timing" not in first["semantic"]


def test_recovery_is_unknown_for_sparse_samples_and_unrecovered_episode(corpus):
    manifest, _ = corpus
    frame = manifest["sequences"][0]["frames"][0]
    hidden = {**frame, "visibility": "hidden", "box": None}
    rows = [{"at": 1, "evaluation": score(hidden, None, .9, manifest["identities"])},
            {"at": 2, "evaluation": score(frame, None, .9, manifest["identities"])},
            {"at": 3, "evaluation": score(frame, player(), .9, manifest["identities"])}]
    assert recovery_delays(rows, False) is None
    assert recovery_delays(rows, True) == [{"reappeared_at": 2,
                                           "fresh_identity_delay_seconds": 1}]
    assert recovery_delays(rows[:2], True)[0]["fresh_identity_delay_seconds"] is None


def test_cli_run_refuses_existing_or_frozen_output_and_preserves_inputs(corpus):
    manifest, root = corpus
    source = root / "manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    output = root / "results/report.json"
    report = run(source, output, root, detector_factory=FakeDetector)
    assert json.loads(output.read_text()) == report
    assert report["manifest_sha256"] == digest(source)
    for protected in (output, source, root / "frame.png", root / "source.py",
                      root / "templates/new-report.json"):
        with pytest.raises(ValueError, match="new file"):
            run(source, protected, root, detector_factory=FakeDetector)
    assert source.read_text() == json.dumps(manifest)
