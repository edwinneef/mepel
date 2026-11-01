"""Read recorded pipeline/input timing without importing capture or native input.

Percentiles use linear interpolation over measured samples, not inferred tail stages.
Input snapshots repeat history and outcomes; controller identity and sequence/ticket
identify unique evidence. Backend submission is not proof the game consumed input.
"""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

STAGES = (
    "capture_interval_ms", "capture_ms", "map_ms", "perception_ms", "position_ms",
    "policy_ms", "annotation_ms", "publish_ms",
)


def number(value, context: str, *, negative: bool = False) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (not negative and value < 0)):
        kind = "number" if negative else "nonnegative number"
        raise ValueError(f"{context}: expected a finite {kind}")
    return float(value)


def integer(value, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context}: expected a nonnegative integer")
    return value


def mapping(value, context: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{context}: expected an object")
    return value


def optional_object(row: dict, field: str) -> dict:
    value = row.get(field)
    return {} if value is None else mapping(value, field)


def distribution(values: list[float], denominator: int) -> dict:
    ordered = sorted(values)

    def percentile(fraction):
        if not ordered:
            return None
        index = (len(ordered) - 1) * fraction
        lo, hi = math.floor(index), math.ceil(index)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)

    return {"samples": len(ordered), "denominator": denominator,
            "missing": denominator - len(ordered),
            "p50": percentile(.5), "p95": percentile(.95), "p99": percentile(.99),
            "max": max(ordered) if ordered else None}


def field_stats(objects: list[dict], name: str, context: str) -> dict:
    values = [number(item[name], f"{context}.{name}") for item in objects
              if item.get(name) is not None]
    return {**distribution(values, len(objects)),
            "absent": sum(name not in item for item in objects),
            "null": sum(name in item and item[name] is None for item in objects)}


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("Nonfinite JSON number")
    return value


def _invalid_constant(text: str):
    raise ValueError(f"Nonfinite JSON constant: {text}")


def _object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_records(path: Path) -> tuple[list[dict], dict]:
    data = path.read_bytes()
    rows = []
    blank = 0
    for line, content in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        if not content.strip():
            blank += 1
            continue
        try:
            row = json.loads(content, parse_float=_finite_float,
                             parse_constant=_invalid_constant, object_pairs_hook=_object)
            rows.append(mapping(row, "record"))
        except ValueError as error:
            raise ValueError(f"Line {line}: {error}") from error
    if not rows:
        raise ValueError("Recording contains no records")
    return rows, {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(),
                  "bytes": len(data), "records": len(rows), "blank_lines": blank}


def capture_timing(rows: list[dict]) -> dict:
    previous = {}
    intervals = []
    wall_rollbacks = 0
    missing = Counter()
    for index, row in enumerate(rows):
        scope = row.get("source_generation")
        if scope is not None:
            integer(scope, f"row {index}.source_generation")
        for key in ("sequence", "capture_clock", "captured_at"):
            if row.get(key) is None:
                missing[key] += 1
            elif key == "sequence":
                integer(row[key], f"row {index}.{key}")
            else:
                number(row[key], f"row {index}.{key}")
        prior = previous.get(scope)
        if prior:
            for key in ("sequence", "capture_clock"):
                if (row.get(key) is not None and prior.get(key) is not None
                        and row[key] <= prior[key]):
                    raise ValueError(f"row {index}.{key}: out of order within source generation")
            if row.get("capture_clock") is not None and prior.get("capture_clock") is not None:
                intervals.append(1000 * (row["capture_clock"] - prior["capture_clock"]))
            if (row.get("captured_at") is not None and prior.get("captured_at") is not None
                    and row["captured_at"] < prior["captured_at"]):
                wall_rollbacks += 1
        previous[scope] = row
    return {
        "missing_fields": {key: missing[key] for key in
                           ("sequence", "capture_clock", "captured_at")},
        "source_generations": len(previous), "wall_clock_rollbacks": wall_rollbacks,
        "recorded_capture_gap_ms": distribution(intervals, len(rows)),
        "observation_age_at_input_ms": None,
        "age_unavailable_reason": "No key-down event with a complete originating observation "
        "and comparable event clock was recorded. Surrounding frame timestamps, ticket outcomes "
        "and session-relative policy times do not substitute for event causality.",
    }


def _event_identity(event: dict, timing: dict):
    identity = event.get("history_id", timing.get("history_id"))
    if identity is not None and (not isinstance(identity, str) or not identity):
        raise ValueError("input event history_id: expected a nonempty string")
    if timing.get("history_id") and identity != timing["history_id"]:
        raise ValueError("Input event and snapshot history_id disagree")
    sequence = event.get("sequence")
    if sequence is not None:
        integer(sequence, "input event sequence")
    return (identity, sequence) if identity is not None and sequence is not None else None


def observation_metadata(value) -> dict | None:
    if value is None:
        return None
    observation = mapping(value, "input observation")
    if observation.get("clock_domain", "perf_counter") != "perf_counter":
        raise ValueError("Input observation clock_domain must be perf_counter")
    for field in ("capture_clock", "deadline"):
        if observation.get(field) is not None:
            number(observation[field], f"input observation.{field}")
    for field in ("source_generation", "view_generation", "sequence"):
        if observation.get(field) is not None:
            integer(observation[field], f"input observation.{field}")
    if (observation.get("deadline") is not None and observation.get("capture_clock") is not None
            and observation["deadline"] < observation["capture_clock"]):
        raise ValueError("Input observation deadline precedes capture_clock")
    return observation


def event_observation(event: dict) -> tuple[dict | None, float | None]:
    if event.get("clock_domain", "perf_counter") != "perf_counter":
        raise ValueError("Input event clock_domain must be perf_counter")
    observation = observation_metadata(event.get("observation"))
    supplied_age = event.get("capture_age_ms")
    if supplied_age is not None:
        number(supplied_age, "input event.capture_age_ms")
    computed_age = None
    if (observation is not None and observation.get("capture_clock") is not None
            and event.get("clock") is not None):
        clock = number(event["clock"], "input event.clock")
        computed_age = number(1000 * (clock - observation["capture_clock"]),
                              "computed input capture age")
        if (supplied_age is not None
                and not math.isclose(computed_age, supplied_age, rel_tol=1e-9, abs_tol=1e-6)):
            raise ValueError("Input capture_age_ms contradicts event and observation clocks")
    return observation, computed_age


def key_down_observations(events: dict, tickets: dict) -> dict:
    """Use explicit original context only; never join against a later frame snapshot."""
    bindings = {}
    for key, outcome in tickets.items():
        observation = observation_metadata(outcome.get("observation"))
        if observation is not None:
            bindings[key] = observation
    evidence, missing = [], Counter()
    down_count = 0
    fields = ("capture_clock", "deadline", "source_generation", "view_generation", "sequence")
    for (history_id, sequence), event in events.items():
        observation, computed_age = event_observation(event)
        ticket = event.get("ticket")
        if ticket is not None:
            integer(ticket, "input event.ticket")
        if observation is not None and ticket is not None:
            key = history_id, ticket
            if key in bindings and bindings[key] != observation:
                raise ValueError("Ticket observation metadata changed between outcome or events")
            bindings[key] = observation
        if event.get("down") is not True:
            continue  # Release after expiry is permitted; it is not a stale key-down.
        down_count += 1
        if observation is None:
            missing["observation"] += 1
        elif ticket is None:
            missing["ticket"] += 1
        elif any(observation.get(field) is None for field in fields):
            missing["incomplete_observation"] += 1
        elif computed_age is None:
            missing["event_clock"] += 1
        else:
            evidence.append({"history_id": history_id, "event_sequence": sequence,
                             "ticket": ticket, "observation": observation,
                             "capture_age_ms": computed_age,
                             "deadline_exceeded": event["clock"] > observation["deadline"]})
    return {"clock_contract": "keyboard InputObservation.capture_clock/deadline and event.clock "
            "are perf_counter seconds; optional explicit clock_domain must agree",
            "key_down_events": down_count, "known_age": len(evidence),
            "unknown_age": down_count - len(evidence), "missing_reasons": dict(missing),
            "age_ms": distribution([item["capture_age_ms"] for item in evidence], down_count),
            "pre_dispatch_deadline_violations": sum(item["deadline_exceeded"] for item in evidence),
            "events": evidence,
            "scope": "Age at backend call start, not game receipt. Key-ups are excluded; "
            "unkeyed event snapshots are excluded from unique-event denominators."}


def input_timing(rows: list[dict]) -> dict:
    events, tickets, history = {}, {}, {}
    snapshot_statuses = Counter()
    unknown_event_observations = missing_input = missing_outcome = unkeyed_tickets = 0
    for row in rows:
        if row.get("input_timing") is None:
            missing_input += 1
        timing = optional_object(row, "input_timing")
        identity = timing.get("history_id")
        if identity is not None and (not isinstance(identity, str) or not identity):
            raise ValueError("input_timing.history_id: expected a nonempty string")
        if identity:
            entry = history.setdefault(identity, {"max_history_dropped": None,
                                                  "missing_history_dropped_snapshots": 0,
                                                  "last_sequence": None})
            if timing.get("history_dropped") is not None:
                dropped = integer(timing["history_dropped"], "history_dropped")
                entry["max_history_dropped"] = max(entry["max_history_dropped"] or 0, dropped)
            else:
                entry["missing_history_dropped_snapshots"] += 1
            if timing.get("history_last_sequence") is not None:
                sequence = integer(timing["history_last_sequence"], "history_last_sequence")
                if entry["last_sequence"] is not None and sequence < entry["last_sequence"]:
                    raise ValueError("Input history_last_sequence regressed")
                entry["last_sequence"] = sequence
        samples = timing.get("history", timing.get("events", []))
        if not isinstance(samples, list):
            raise ValueError("input history/events: expected a list")
        previous_sequence = None
        for sample in samples:
            event = mapping(sample, "input event")
            event_observation(event)  # Validate even snapshots lacking a deduplication identity.
            key = _event_identity(event, timing)
            for field in ("clock", "finished_clock", "issued_at", "at_seconds"):
                if event.get(field) is not None:
                    number(event[field], f"input event.{field}")
            if "down" in event and not isinstance(event["down"], bool):
                raise ValueError("input event.down: expected a boolean")
            if event.get("clock") is not None and event.get("finished_clock") is not None:
                if event["finished_clock"] < event["clock"]:
                    raise ValueError("Input event finished before it started")
            if key is None:
                unknown_event_observations += 1
                continue
            if previous_sequence is not None and key[1] <= previous_sequence:
                raise ValueError("Input events are out of sequence within a snapshot")
            previous_sequence = key[1]
            if key in events and events[key] != event:
                raise ValueError("Conflicting repeated input event")
            events[key] = event
        if row.get("action_outcome") is None:
            missing_outcome += 1
            continue
        outcome = mapping(row["action_outcome"], "action_outcome")
        observation_metadata(outcome.get("observation"))
        status = outcome.get("status", "missing")
        if not isinstance(status, str):
            raise ValueError("action_outcome.status: expected a string")
        snapshot_statuses[status] += 1
        if outcome.get("ticket") is None:
            continue
        ticket = integer(outcome["ticket"], "ticket")
        for field in ("submitted_at", "started_at", "finished_at"):
            if outcome.get(field) is not None:
                number(outcome[field], f"action_outcome.{field}")
        for first, last in (("submitted_at", "started_at"), ("started_at", "finished_at"),
                            ("submitted_at", "finished_at")):
            if (outcome.get(first) is not None and outcome.get(last) is not None
                    and outcome[last] < outcome[first]):
                raise ValueError(f"Ticket {ticket}: {last} precedes {first}")
        if not identity:
            unkeyed_tickets += 1
            continue
        key = identity, ticket
        prior = tickets.get(key, {})
        for field in ("generation", "action", "submitted_at", "started_at", "finished_at",
                      "observation"):
            if (prior.get(field) is not None and outcome.get(field) is not None
                    and prior[field] != outcome[field]):
                raise ValueError(f"Ticket {ticket}: conflicting repeated {field}")
        if prior.get("finished_at") is not None and outcome.get("finished_at") is None:
            raise ValueError(f"Ticket {ticket}: terminal outcome regressed")
        if (prior.get("finished_at") is not None and outcome.get("finished_at") is not None
                and any(prior.get(field) != outcome.get(field) for field in ("status", "result"))):
            raise ValueError(f"Ticket {ticket}: conflicting terminal outcome")
        tickets[key] = {**prior, **outcome}
    for identity in {key[0] for key in events}:
        clocks = [event["clock"] for key, event in sorted(events.items())
                  if key[0] == identity and event.get("clock") is not None]
        if any(later < earlier for earlier, later in zip(clocks, clocks[1:], strict=False)):
            raise ValueError("Input event clocks regressed across sequences")
    backend = [1000 * (event["finished_clock"] - event["clock"]) for event in events.values()
               if event.get("clock") is not None and event.get("finished_clock") is not None]
    measurements = {}
    for name, first, last in (("submit_to_worker_start_ms", "submitted_at", "started_at"),
                              ("submit_to_finish_ms", "submitted_at", "finished_at"),
                              ("worker_start_to_finish_ms", "started_at", "finished_at")):
        values = [1000 * (item[last] - item[first]) for item in tickets.values()
                  if item.get(first) is not None and item.get(last) is not None]
        measurements[name] = distribution(values, len(tickets))
    interrupted = [item for item in tickets.values()
                   if str(item.get("result", "")).endswith(" interrupted")
                   or item.get("status") in {"cancelled", "canceled", "interrupted"}]
    return {
        "missing_input_timing_rows": missing_input, "missing_action_outcome_rows": missing_outcome,
        "action_status_snapshot_counts": dict(sorted(snapshot_statuses.items())),
        "controller_history": history, "unique_backend_events": len(events),
        "key_down_events": sum(event.get("down") is True for event in events.values()),
        "key_up_events": sum(event.get("down") is False for event in events.values()),
        "unkeyed_event_observations_excluded": unknown_event_observations,
        "backend_call_ms": distribution(backend, len(events)),
        "unique_observed_tickets": len(tickets),
        "unkeyed_ticket_snapshots_excluded": unkeyed_tickets,
        "ticket_status_counts": dict(Counter(item.get("status", "missing")
                                             for item in tickets.values())),
        "interrupted_or_cancelled_tickets": len(interrupted),
        "interrupted_before_worker_start": sum(item.get("started_at") is None
                                                and item.get("finished_at") is not None
                                                and "started_at" in item for item in interrupted),
        "ticket_timing_ms": measurements,
        "key_down_observation_evidence": key_down_observations(events, tickets),
    }


def analyze(path: Path) -> dict:
    rows, provenance = read_records(path)
    stages = [optional_object(row, "stage_timing") for row in rows]
    names = set(STAGES).union(*(stage.keys() for stage in stages))
    if any(not name.endswith("_ms") for name in names):
        raise ValueError("stage_timing: expected millisecond fields ending in _ms")
    encoders = [optional_object(row, "encoder") for row in rows]
    input_report = input_timing(rows)
    capture_report = capture_timing(rows)
    ages = input_report["key_down_observation_evidence"]
    if ages["known_age"]:
        capture_report["observation_age_at_input_ms"] = ages["age_ms"]
        capture_report["age_unavailable_reason"] = None
    return {
        "version": 1, "provenance": provenance,
        "percentile_method": "linear interpolation at (n - 1) * quantile; milliseconds",
        "stages_ms": {name: field_stats(stages, name, "stage_timing") for name in sorted(names)},
        "loop_to_processed_ms": field_stats(rows, "latency_ms", "record"),
        "png_encode_callback_ms": field_stats(encoders, "png_encode_ms", "encoder"),
        "capture": capture_report, "input": input_report,
        "limitations": [
            "Only recorded samples are measured; absent/null timings are not zero.",
            "Stages overlap or omit work. No summed end-to-end latency is reported. latency_ms "
            "runs from loop start through processing, before publishing/encoding/recording.",
            "Runtime _encoded overwrites png_encode_ms with this packet callback elapsed. "
            "Encoder snapshot encoded_sequence may still identify the preceding packet.",
            "Queueing, JSONL writing, PNG writing, HTTP transfer and UI rendering tail times are "
            "not recorded here. Existing publish_ms measures copies and enqueueing only.",
            "Recorded capture gaps may include dropped/unrecorded frames or generation changes; "
            "they are not necessarily capture cadence. Wall-clock rollback is diagnostic only.",
            "Input history is bounded; repeated snapshots are deduplicated by controller and "
            "event sequence. Dropped history does not prove this recording missed those events.",
            "Ticket worker start is not first key dispatch. Schedule reaction delays are included "
            "in worker duration. Last-outcome snapshots can miss intermediate tickets.",
            "Capture-to-key-down age uses only explicit event observation metadata. Older or "
            "incomplete events remain unknown; newer frame contexts cannot renew their origin. "
            "Deadline violations compare recorded backend-call start with the original deadline.",
            "Interrupted outcomes establish interruption, not its cause, cancellation request "
            "time or stop-to-release latency. No complete ticket lifecycle is inferred.",
            "Successful backend submission is not game input consumption, movement "
            "or hit evidence.",
            "This offline reader imports no application/native modules and sends no input.",
        ],
    }


def run(source: Path, output: Path) -> dict:
    if output.exists() or output.resolve() == source.resolve():
        raise ValueError("Output must be a new path; existing evidence cannot be overwritten")
    report = analyze(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Recorded decisions.jsonl")
    parser.add_argument("--output", required=True, type=Path, help="New JSON report path")
    args = parser.parse_args()
    try:
        report = run(args.input, args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Timing report failed: {error}\n")
    print(f"Reported {report['provenance']['records']} recorded frames to {args.output}")


if __name__ == "__main__":
    main()
