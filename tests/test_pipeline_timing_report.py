import copy
import hashlib
import json

import pytest

from tools.pipeline_timing_report import analyze, distribution, run


def recording(tmp_path, rows):
    path = tmp_path / "decisions.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def frame(sequence=0, clock=10.0):
    return {"sequence": sequence, "source_generation": 1, "capture_clock": clock,
            "captured_at": 1_800_000_000 + clock,
            "stage_timing": {"capture_ms": 2, "perception_ms": 8},
            "input_timing": {"history_id": "controller-a", "history": [],
                             "history_last_sequence": 0, "history_dropped": 0},
            "action_outcome": {"status": "not_sent"}}


def event(sequence=1, clock=10.1):
    return {"sequence": sequence, "history_id": "controller-a", "clock": clock,
            "finished_clock": clock + .002, "issued_at": 1_800_000_000 + clock,
            "key": "right", "down": True, "at_seconds": .03}


def test_measured_percentiles_missing_and_provenance(tmp_path):
    rows = [frame(i, 10 + i * .2) for i in range(3)]
    rows[0]["stage_timing"]["perception_ms"] = 10
    rows[1]["stage_timing"]["perception_ms"] = None
    del rows[2]["stage_timing"]["perception_ms"]
    rows[0]["encoder"] = {"png_encode_ms": 7, "encoded_sequence": -1}
    path = recording(tmp_path, rows)
    report = analyze(path)
    assert report["provenance"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["stages_ms"]["perception_ms"] == {
        "samples": 1, "denominator": 3, "missing": 2, "absent": 1, "null": 1,
        "p50": 10, "p95": 10, "p99": 10, "max": 10,
    }
    assert report["stages_ms"]["publish_ms"]["samples"] == 0
    assert report["stages_ms"]["publish_ms"]["p99"] is None
    # Callback latency belongs to the current row despite prior encoder sequence.
    assert report["png_encode_callback_ms"]["samples"] == 1
    assert report["png_encode_callback_ms"]["p50"] == 7
    assert report["capture"]["recorded_capture_gap_ms"]["p95"] == pytest.approx(200)
    assert report["capture"]["observation_age_at_input_ms"] is None
    assert distribution([0, 10, 20, 30], 4)["p95"] == pytest.approx(28.5)


def test_repeated_input_snapshots_are_not_repeated_dispatches_or_tickets(tmp_path):
    rows = [frame(i, 10 + i) for i in range(3)]
    rows[0]["action_outcome"] = {"status": "pending", "ticket": 1}
    outcome = {"status": "completed", "ticket": 1, "generation": 2, "action": "right",
               "result": "right completed", "submitted_at": 10.0,
               "started_at": 10.01, "finished_at": 10.15}
    for row in rows[1:]:
        row["action_outcome"] = copy.deepcopy(outcome)
        row["input_timing"].update(history=[event()], history_last_sequence=1)
    report = analyze(recording(tmp_path, rows))["input"]
    assert report["unique_backend_events"] == report["key_down_events"] == 1
    assert report["unique_observed_tickets"] == 1
    assert report["backend_call_ms"]["p50"] == pytest.approx(2)
    assert report["ticket_timing_ms"]["submit_to_worker_start_ms"]["p99"] == pytest.approx(10)
    assert report["action_status_snapshot_counts"] == {"completed": 2, "pending": 1}
    assert report["ticket_status_counts"] == {"completed": 1}


def test_cancelled_before_worker_start_is_distinct_from_dispatch(tmp_path):
    row = frame()
    row["action_outcome"] = {"status": "completed", "ticket": 3,
                             "result": "attack interrupted", "submitted_at": 10,
                             "started_at": None, "finished_at": 10.1}
    report = analyze(recording(tmp_path, [row]))["input"]
    assert report["interrupted_or_cancelled_tickets"] == 1
    assert report["interrupted_before_worker_start"] == 1
    assert report["unique_backend_events"] == 0
    assert report["ticket_timing_ms"]["submit_to_worker_start_ms"]["samples"] == 0
    assert report["ticket_timing_ms"]["submit_to_finish_ms"]["p50"] == pytest.approx(100)


def test_missing_clock_or_identity_does_not_fabricate_age_or_deduplicate(tmp_path):
    row = {"input_timing": {"events": [{"key": "left", "down": True}]},
           "action_outcome": {"status": "pending", "ticket": 5}}
    report = analyze(recording(tmp_path, [row, row]))
    assert report["capture"]["missing_fields"]["capture_clock"] == 2
    assert report["capture"]["recorded_capture_gap_ms"]["samples"] == 0
    assert report["input"]["unique_backend_events"] == 0
    assert report["input"]["unkeyed_event_observations_excluded"] == 2
    assert report["input"]["unkeyed_ticket_snapshots_excluded"] == 2
    assert report["input"]["unique_observed_tickets"] == 0


def test_wall_clock_rollback_is_not_confused_with_monotonic_time(tmp_path):
    rows = [frame(0, 10), frame(1, 11)]
    rows[1]["captured_at"] = rows[0]["captured_at"] - 1
    report = analyze(recording(tmp_path, rows))["capture"]
    assert report["wall_clock_rollbacks"] == 1
    assert report["recorded_capture_gap_ms"]["p50"] == 1000
    assert report["observation_age_at_input_ms"] is None


@pytest.mark.parametrize("content", ["{bad}", "[]", '{"sequence": NaN}',
                                     '{"x": 1e999}', '{"x":1,"x":2}', "\n"])
def test_malformed_or_nonfinite_json_is_rejected(tmp_path, content):
    path = tmp_path / "bad.jsonl"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        analyze(path)


@pytest.mark.parametrize("field,value", [("capture_ms", -1), ("map_ms", "3"),
                                        ("policy_ms", True), ("unknown_unit", 2)])
def test_invalid_stage_schema_is_rejected(tmp_path, field, value):
    row = frame()
    row["stage_timing"][field] = value
    with pytest.raises(ValueError):
        analyze(recording(tmp_path, [row]))


@pytest.mark.parametrize("field", ["stage_timing", "encoder", "input_timing", "action_outcome"])
def test_empty_nonobject_fields_are_rejected(tmp_path, field):
    row = frame()
    row[field] = []
    with pytest.raises(ValueError, match="expected an object"):
        analyze(recording(tmp_path, [row]))


@pytest.mark.parametrize("field,value", [("sequence", 0), ("capture_clock", 9)])
def test_out_of_order_capture_records_are_rejected(tmp_path, field, value):
    rows = [frame(0, 10), frame(1, 11)]
    rows[1][field] = value
    with pytest.raises(ValueError, match="out of order"):
        analyze(recording(tmp_path, rows))


def test_generation_boundary_does_not_produce_a_false_capture_gap(tmp_path):
    rows = [frame(0, 10), frame(0, 3)]
    rows[1]["source_generation"] = 2
    report = analyze(recording(tmp_path, rows))["capture"]
    assert report["recorded_capture_gap_ms"]["samples"] == 0
    assert report["source_generations"] == 2


def test_input_history_conflicts_and_order_are_rejected(tmp_path):
    rows = [frame(0, 10), frame(1, 11)]
    for row in rows:
        row["input_timing"].update(history=[event()], history_last_sequence=1)
    rows[1]["input_timing"]["history"][0]["key"] = "left"
    with pytest.raises(ValueError, match="Conflicting repeated"):
        analyze(recording(tmp_path, rows))
    rows[1]["input_timing"]["history"] = [event(2, 10.4), event(1, 10.1)]
    with pytest.raises(ValueError, match="out of sequence"):
        analyze(recording(tmp_path, rows))


def test_invalid_ticket_times_and_regressed_terminal_status_are_rejected(tmp_path):
    row = frame()
    row["action_outcome"] = {"status": "completed", "ticket": 1, "submitted_at": 11,
                             "started_at": 10, "finished_at": 12}
    with pytest.raises(ValueError, match="precedes"):
        analyze(recording(tmp_path, [row]))
    row["action_outcome"]["submitted_at"] = 9
    later = frame(1, 11)
    later["action_outcome"] = {"status": "pending", "ticket": 1}
    with pytest.raises(ValueError, match="terminal outcome regressed"):
        analyze(recording(tmp_path, [row, later]))


def test_historical_evictions_and_controller_identities_remain_separate(tmp_path):
    rows = [frame(0, 10), frame(1, 11)]
    rows[0]["input_timing"].update(history=[event()], history_last_sequence=1)
    another = event()
    another["history_id"] = "controller-b"
    rows[1]["input_timing"].update(history_id="controller-b", history=[another],
                                    history_last_sequence=1, history_dropped=4)
    report = analyze(recording(tmp_path, rows))["input"]
    assert report["unique_backend_events"] == 2
    assert report["controller_history"]["controller-b"]["max_history_dropped"] == 4


def test_missing_history_completeness_is_unknown(tmp_path):
    row = frame()
    del row["input_timing"]["history_dropped"]
    report = analyze(recording(tmp_path, [row]))["input"]
    history = report["controller_history"]["controller-a"]
    assert history["max_history_dropped"] is None
    assert history["missing_history_dropped_snapshots"] == 1


def test_conflicting_terminal_outcome_is_rejected(tmp_path):
    rows = [frame(0, 10), frame(1, 11)]
    for row in rows:
        row["action_outcome"] = {"status": "completed", "ticket": 1, "submitted_at": 10,
                                 "started_at": 10.1, "finished_at": 10.2,
                                 "result": "right completed"}
    rows[1]["action_outcome"]["result"] = "right interrupted"
    with pytest.raises(ValueError, match="conflicting terminal"):
        analyze(recording(tmp_path, rows))


def test_run_writes_only_new_output_and_is_deterministic(tmp_path):
    source = recording(tmp_path, [frame()])
    before = source.read_bytes()
    output = tmp_path / "reports" / "report.json"
    report = run(source, output)
    assert json.loads(output.read_text()) == report == analyze(source)
    assert source.read_bytes() == before
    with pytest.raises(ValueError, match="new path"):
        run(source, output)
    with pytest.raises(ValueError, match="new path"):
        run(source, source)


def observation(captured=10.0, deadline=10.5, sequence=4):
    return {"capture_clock": captured, "deadline": deadline,
            "source_generation": 1, "view_generation": 2, "sequence": sequence}


def observed_event(sequence=1, clock=10.1, *, down=True):
    item = event(sequence, clock)
    item.update(ticket=8, observation=observation(), capture_age_ms=(clock - 10) * 1000,
                down=down)
    return item


def test_mixed_old_and_new_events_have_explicit_causal_age_denominators(tmp_path):
    row = frame(20, 12)
    row["input_timing"].update(history=[event(1, 10.05), observed_event(2, 10.1)],
                               history_last_sequence=2)
    # A later frame context cannot become the earlier ticket's capture origin.
    row.update(view_generation=3, source_generation=3)
    report = analyze(recording(tmp_path, [row, {**row, "sequence": 21, "capture_clock": 13}]))
    age = report["input"]["key_down_observation_evidence"]
    assert age["key_down_events"] == 2
    assert age["known_age"] == age["unknown_age"] == 1
    assert age["missing_reasons"] == {"observation": 1}
    assert age["age_ms"]["p50"] == pytest.approx(100)
    assert age["events"][0]["observation"] == observation()
    assert age["pre_dispatch_deadline_violations"] == 0
    assert report["capture"]["observation_age_at_input_ms"] == age["age_ms"]
    assert report["capture"]["age_unavailable_reason"] is None


def test_deadline_violations_apply_to_key_down_only(tmp_path):
    row = frame()
    row["input_timing"].update(history=[observed_event(1, 10.5), observed_event(2, 10.6),
                                        observed_event(3, 11, down=False)],
                               history_last_sequence=3)
    report = analyze(recording(tmp_path, [row]))["input"]["key_down_observation_evidence"]
    assert report["known_age"] == 2
    assert report["pre_dispatch_deadline_violations"] == 1
    assert report["age_ms"]["max"] == pytest.approx(600)


def test_outcome_context_alone_cannot_establish_key_down_age(tmp_path):
    row = frame()
    row["input_timing"].update(history=[event()], history_last_sequence=1)
    row["action_outcome"] = {"status": "pending", "ticket": 8, "observation": observation()}
    report = analyze(recording(tmp_path, [row]))
    assert report["capture"]["observation_age_at_input_ms"] is None
    age = report["input"]["key_down_observation_evidence"]
    assert age["known_age"] == 0 and age["unknown_age"] == 1


@pytest.mark.parametrize("change", ["wrong_age", "wall_domain", "negative_age", "bad_deadline",
                                    "bad_sequence", "nan_age"])
def test_invalid_or_contradictory_observation_metadata_is_rejected(tmp_path, change):
    item = observed_event()
    if change == "wrong_age":
        item["capture_age_ms"] = 700
    elif change == "wall_domain":
        item["observation"]["clock_domain"] = "wall"
    elif change == "negative_age":
        item["clock"] = 9
    elif change == "bad_deadline":
        item["observation"]["deadline"] = 9
    elif change == "bad_sequence":
        item["observation"]["sequence"] = True
    else:
        item["capture_age_ms"] = float("nan")
    row = frame()
    row["input_timing"].update(history=[item], history_last_sequence=1)
    with pytest.raises(ValueError):
        analyze(recording(tmp_path, [row]))


def test_same_ticket_cannot_rebind_to_new_observation_in_event_or_outcome(tmp_path):
    row = frame()
    first, second = observed_event(1, 10.1), observed_event(2, 10.2)
    second["observation"]["sequence"] = 5
    row["input_timing"].update(history=[first, second], history_last_sequence=2)
    with pytest.raises(ValueError, match="metadata changed"):
        analyze(recording(tmp_path, [row]))
    row["input_timing"]["history"] = [first]
    row["action_outcome"] = {"status": "pending", "ticket": 8,
                             "observation": observation(sequence=5)}
    with pytest.raises(ValueError, match="metadata changed"):
        analyze(recording(tmp_path, [row]))


def test_missing_observation_field_stays_unknown_and_supplied_age_is_optional(tmp_path):
    first, second = observed_event(1, 10.1), observed_event(2, 10.2)
    del first["capture_age_ms"]
    del second["observation"]["sequence"]
    second["ticket"] = 9
    row = frame()
    row["input_timing"].update(history=[first, second], history_last_sequence=2)
    report = analyze(recording(tmp_path, [row]))["input"]["key_down_observation_evidence"]
    assert report["known_age"] == report["unknown_age"] == 1
    assert report["missing_reasons"] == {"incomplete_observation": 1}
    assert report["age_ms"]["p50"] == pytest.approx(100)


def test_unkeyed_event_still_rejects_contradictory_clock_metadata(tmp_path):
    item = observed_event()
    del item["history_id"]
    del item["sequence"]
    item["capture_age_ms"] = 999
    with pytest.raises(ValueError, match="contradicts"):
        analyze(recording(tmp_path, [{"input_timing": {"events": [item]}}]))
