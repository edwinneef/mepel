import json
import sys
from dataclasses import replace

import pytest

from tools import monster_association_experiment as experiment


@pytest.fixture(scope="module")
def results():
    return {case.name: experiment.compare_case(case) for case in experiment.cases()}


def test_competition_exposes_cardinality_loss_without_relaxing_gates(results):
    case = results["competition"]
    assert case["baseline_mirror_matches_actual"]
    assert case["baseline"]["assigned"] == 1
    assert case["baseline"]["id_switches"] == 1
    assert case["reference"]["assigned"] == case["reference"]["correct_existing_ids"] == 2
    assert case["reference"]["id_switches"] == 0
    assert case["baseline"]["births"] == case["reference"]["births"] == 0
    assert case["feasible_edges"] == case["eligible_after_ambiguity_veto"]


def test_global_cost_alone_does_not_resolve_true_crossing(results):
    case = results["true_crossing"]
    for strategy in ("baseline", "reference"):
        assert case[strategy]["id_switches"] == 2
        assert case[strategy]["correct_existing_ids"] == 0
    assert case["baseline"] == case["reference"]


def test_ambiguity_veto_prevents_assignments_and_duplicate_births(results):
    case = results["ambiguous_overlap"]
    assert case["feasible_edges"] and not case["eligible_after_ambiguity_veto"]
    for strategy in ("baseline", "reference"):
        assert case[strategy]["assigned"] == case[strategy]["births"] == 0
        assert case[strategy]["unassigned_confirmed"] == 2


@pytest.mark.parametrize("name", ["weak_clutter", "tracked_only_clutter"])
def test_weak_or_predicted_detections_never_create_new_targets(results, name):
    for strategy in ("baseline", "reference"):
        assert results[name][strategy]["births"] == 0
        assert results[name][strategy]["weak_or_predicted_assigned"] == 0
        assert results[name][strategy]["correct_existing_ids"] == 1


def test_construction_truth_distinguishes_false_births_from_real_new_actors(results):
    for strategy in ("baseline", "reference"):
        assert results["new_actor"][strategy]["births"] == 1
        assert results["new_actor"][strategy]["unsupported_births"] == 0
        assert results["high_confidence_clutter"][strategy]["births"] == 1
        assert results["high_confidence_clutter"][strategy]["unsupported_births"] == 1


def test_truth_labels_do_not_change_assignments():
    case = next(case for case in experiment.cases() if case.name == "competition")
    renamed = replace(case, observations=tuple(replace(s, actor="different")
                                               for s in case.observations))
    original, changed = experiment.compare_case(case), experiment.compare_case(renamed)
    assert [(s["baseline_id"], s["reference_id"]) for s in original["observations"]] == [
        (s["baseline_id"], s["reference_id"]) for s in changed["observations"]
    ]
    assert original["feasible_edges"] == changed["feasible_edges"]


def test_species_gate_is_shared_with_real_tracker():
    snail = experiment.Sample("snail", 100)
    pig = experiment.Sample("pig", 100, template="catalog:Pig:move-0")
    case = experiment.Case("species", (snail, pig), (replace(pig, x=101),
                                                   replace(snail, x=102)), "Species gate")
    result = experiment.compare_case(case)
    assert len(result["feasible_edges"]) == 2
    assert result["baseline"] == result["reference"]
    assert result["baseline"]["correct_existing_ids"] == 2


def test_global_assignment_uses_cardinality_then_cost_and_is_bounded():
    # Greedy selects (track 0, detection 0); global keeps both tracks assigned.
    edges = [(.1, 0, 0), (.7, 0, 1), (.4, 1, 0)]
    assert experiment.greedy_assignment(edges) == {0: 0}
    assert experiment.global_assignment(edges, 2, 2) == {0: 1, 1: 0}
    assert experiment.global_assignment([(.9, 0, 0), (.1, 0, 1)], 1, 2) == {1: 0}
    dense = [(1., i, j) for i in range(6) for j in range(6)]
    assert experiment.global_assignment(dense, 6, 6) == {i: i for i in range(6)}
    with pytest.raises(ValueError, match="limited"):
        experiment.global_assignment([], 7, 1)
    with pytest.raises(ValueError, match="Invalid"):
        experiment.global_assignment([(float("nan"), 0, 0)], 1, 1)


def test_mirrored_baseline_drift_stops_comparison(monkeypatch):
    monkeypatch.setattr(experiment, "greedy_assignment", lambda _: {})
    with pytest.raises(ValueError, match="drifted"):
        experiment.compare_case(experiment.cases()[0])


def test_report_records_synthetic_scope_timing_and_no_promotion():
    report = experiment.experiment(repeats=2)
    assert report["input_sent"] is False and report["promotion"] == "deferred"
    assert report["evidence"] == "synthetic_fixed_detections"
    assert len(report["source_sha256"]) == 64
    assert len(report["cases"]) == 8
    assert report["processing_seconds"] >= 0
    for case in report["cases"]:
        assert case["baseline_mirror_matches_actual"]
        assert all(t["samples"] == 2 and t["p50"] >= 0 for t in case["timing_ms"].values())
    json.dumps(report, allow_nan=False)
    with pytest.raises(ValueError, match="repeats"):
        experiment.experiment(1001)


def test_cli_preserves_existing_report(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text("original", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["experiment", "--repeats", "1", "--output", str(path)])
    with pytest.raises(FileExistsError):
        experiment.main()
    assert path.read_text("utf-8") == "original"
