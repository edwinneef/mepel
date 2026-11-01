import copy
import json
import math

import pytest

from maplebot.geometry import Rect
from tools.player_recovery_experiments import (
    TimedSearchPredictor,
    experiment_report,
    glyph_experiment,
    interval_filter,
    prediction_experiment,
    run,
    synthetic_sequences,
)


@pytest.fixture
def predictions():
    return {item["id"]: prediction_experiment(item) for item in synthetic_sequences()}


def test_timestamp_normalization_changes_irregular_cadence_not_regular(predictions):
    regular = predictions["regular"]["missing_frame_summary"]
    assert regular["baseline"]["mean_error_px"] == regular["candidate"]["mean_error_px"] == 0
    irregular = predictions["irregular"]["missing_frame_summary"]
    assert irregular["baseline"]["mean_error_px"] > 0
    assert irregular["candidate"]["mean_error_px"] == 0
    assert irregular["candidate"]["predictions_scored"] == 2


def test_constant_velocity_cannot_predict_unobserved_stops_or_reversals(predictions):
    for name in ("stopped", "reversal"):
        summary = predictions[name]["missing_frame_summary"]
        assert summary["candidate"]["mean_error_px"] > 0
        assert summary["candidate"]["mean_error_px"] == summary["baseline"]["mean_error_px"]


def test_camera_and_horizon_abstention_is_explicit(predictions):
    assert predictions["camera_scroll"]["missing_frame_summary"]["candidate"]["mean_error_px"] == 0
    for name in ("camera_loss", "long_gap"):
        summary = predictions[name]["missing_frame_summary"]
        assert summary["candidate"]["abstained"] == 2
        assert summary["candidate"]["mean_error_px"] is None
        assert summary["baseline"]["predictions_scored"] == 2
    rows = predictions["camera_loss"]["results"]
    assert rows[1]["candidate_reason"] == "camera_uncertain"
    assert rows[2]["candidate_reason"] == "camera_needs_observation"


def test_every_prediction_preserves_evidence_age_and_confidence(predictions):
    for sequence in predictions.values():
        for row in sequence["results"]:
            assert row["evidence_before"] == row["evidence_after_prediction"]
            assert row["identity_confirmed_by_prediction"] is False
            if row["at"] > .1 and not row["observed"]:
                assert row["evidence_after_prediction"]["baseline"] == [.1, .1, .99]
                assert row["evidence_after_prediction"]["candidate"] == [.1, .1, .99]


def test_candidate_speed_and_displacement_bounds():
    candidate = TimedSearchPredictor(Rect(0, 0, 20, 30), max_displacement=30)
    candidate.predict(.1, (0, 0), 1)
    candidate.observe(Rect(100, 0, 20, 30), .1)
    assert candidate.velocity == (240, 0)
    box, reason = candidate.predict(.5, (0, 0), 1)
    assert box.x == 130 and reason == "search_only"
    assert candidate.seen == candidate.confirmed == .1


@pytest.mark.parametrize("timestamp", [.1, 0, float("nan"), float("inf")])
def test_invalid_sequence_timestamps_are_rejected(timestamp):
    sequence = copy.deepcopy(synthetic_sequences()[0])
    sequence["frames"][2]["at"] = timestamp
    with pytest.raises(ValueError, match="strictly increasing"):
        prediction_experiment(sequence)


def test_glyph_ablation_reports_actual_scores_without_identity_promotion():
    report = glyph_experiment()
    cases = {case["id"]: case for case in report["cases"]}
    def raw(name):
        return cases[name]["scores"]["raw"]["at_constructed_origin"]

    assert raw("complete") == pytest.approx(1, abs=1e-5)
    assert raw("left_occlusion") < raw("complete")
    assert raw("bottom_occlusion") < raw("complete")
    assert raw("cloud") < raw("complete")
    assert cases["shared_prefix"]["kind"] == cases["adjacent_names"]["kind"] == "negative"
    for case in cases.values():
        assert case["identity_confirmed"] is False
        assert set(case["scores"]) == {"raw", "opening_2x2", "closing_3x3"}
        for variant in case["scores"].values():
            assert math.isfinite(variant["peak"]) and -.00001 <= variant["peak"] <= 1.00001
    # Removing thin glyphs is observable rather than assumed to improve the primitive.
    assert cases["complete"]["scores"]["opening_2x2"]["peak"] < raw("complete")


def test_supplied_intervals_only_reject_and_abstain_when_unreliable():
    assert interval_filter(100, (80, 120), .1) == "retain_unconfirmed"
    assert interval_filter(60, (80, 120), .1) == "reject"
    assert interval_filter(160, (80, 120), .1) == "reject"
    assert interval_filter(160, (80, 120), .3) == "abstain"
    assert interval_filter(160, (80, 120), .1, ambiguous=True) == "abstain"
    assert interval_filter(160, (80, 120), .1, camera_known=False) == "abstain"
    assert interval_filter(160, None, .1) == "abstain"
    assert interval_filter(100, (120, 80), .1) == "abstain"
    assert interval_filter(100, (80, 120), float("nan")) == "abstain"


def test_report_has_source_hashes_and_writes_only_new_output(tmp_path):
    report = experiment_report()
    assert report["scope"] == "synthetic-only offline primitive ablations"
    assert len(report["source_sha256"]) == 3
    assert all(len(value) == 64 for value in report["source_sha256"].values())
    output = tmp_path / "result.json"
    run(output)
    # JSON serialization turns the supplied interval tuples into arrays.
    assert json.loads(output.read_text()) == json.loads(json.dumps(report))
    assert experiment_report() == report
    with pytest.raises(ValueError, match="new path"):
        run(output)
