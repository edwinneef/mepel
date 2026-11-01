"""Input-free, constructed one-transition enemy-association comparison.

Uses the actual EnemyTracker for the baseline. The exhaustive reference shares
its species, distance, ambiguity and birth gates, but does not replace the runtime
tracker or propagate counterfactual state across frames. Construction identities
are labels only and never enter either matching strategy.
"""

import argparse
import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import maplebot.enemy_tracking as enemy_tracking
from maplebot.config import PerceptionConfig
from maplebot.enemy_tracking import EnemyTracker, species
from maplebot.geometry import Rect
from maplebot.perception import Detection

MAX_TARGETS = 6


@dataclass(frozen=True)
class Sample:
    actor: str | None
    x: int
    confidence: float = .99
    template: str = "catalog:Snail:move-0"
    tracked: bool = False

    def detection(self) -> Detection:
        return Detection("monster", Rect(self.x - 10, 70, 20, 30), self.confidence,
                         self.template, tracked=self.tracked)


@dataclass(frozen=True)
class Case:
    name: str
    initial: tuple[Sample, ...]
    observations: tuple[Sample, ...]
    note: str


def cases() -> tuple[Case, ...]:
    pair = (Sample("a", 100), Sample("b", 140))
    return (
        Case("separated_motion", (Sample("a", 100), Sample("b", 200)),
             (Sample("a", 110), Sample("b", 190)), "Distinct spatial support."),
        Case("competition", pair, (Sample("a", 70), Sample("b", 115)),
             "Greedy consumes the only feasible observation for the second track."),
        Case("true_crossing", pair, (Sample("a", 130), Sample("b", 110)),
             "Both distance-only strategies can prefer the wrong identities."),
        Case("ambiguous_overlap", pair, (Sample("a", 118), Sample("b", 122)),
             "Existing local ambiguity veto must remain effective."),
        Case("weak_clutter", (Sample("a", 100),),
             (Sample("a", 110), Sample(None, 300, .4), Sample(None, 350, .89)),
             "Below-threshold clutter cannot create new tracks."),
        Case("high_confidence_clutter", (Sample("a", 100),),
             (Sample("a", 110), Sample(None, 300)),
             "Matching alone cannot identify a confident false detection."),
        Case("new_actor", (Sample("a", 100),), (Sample("a", 110), Sample("b", 300)),
             "An isolated genuine detection may create a supported new identity."),
        Case("tracked_only_clutter", (Sample("a", 100),),
             (Sample("a", 110), Sample(None, 300, tracked=True)),
             "A prediction passed as a detection cannot create a new track."),
    )


def feasible_edges(tracker, detections):
    """Mirror EnemyTracker.update's inspected full-observation cost and gates.

    Kept in this offline tool only. Every experiment checks mirrored greedy
    assignments against the real tracker, so drift is reported as an error.
    """
    full = [(j, item) for j, item in enumerate(detections)
            if item.confidence >= tracker.config.confidence and not item.tracked]
    if len(tracker.tracks) > MAX_TARGETS or len(detections) > MAX_TARGETS:
        raise ValueError(f"Experiment is limited to {MAX_TARGETS} tracks and detections")
    edges = []
    for i, track in enumerate(tracker.tracks):
        for j, item in full:
            if species(item.template) != species(track.detection.template):
                continue
            x, y = tracker._ground(item.box.center[0], item.box.feet)
            dx, dy = abs(x - track.ground[0]), abs(y - track.ground[1])
            ux, uy = track.uncertainty
            if dx <= min(180, ux + 18) and dy <= min(36, uy + 10):
                score = dx / (ux + 18) + dy / (uy + 10) + .2 * (1 - item.confidence)
                edges.append((score, i, j))
    eligible = [(score, i, j) for score, i, j in edges
                if not any(abs(other - score) < .18 and (a == i or b == j)
                           for other, a, b in edges if (a, b) != (i, j))]
    return full, edges, eligible


def greedy_assignment(edges):
    assigned, used = {}, set()
    for _, i, j in sorted(edges):
        if i not in used and j not in assigned:
            assigned[j] = i
            used.add(i)
    return assigned


def global_assignment(edges, track_count, detection_count):
    """Maximize feasible matches, then minimize cost, with deterministic ties.

    Exhaustive search is intentionally bounded; this is a reference solver,
    not a runtime algorithm or a model of identity certainty.
    """
    if not (0 <= track_count <= MAX_TARGETS and 0 <= detection_count <= MAX_TARGETS):
        raise ValueError(f"Experiment is limited to {MAX_TARGETS} tracks and detections")
    if any(not math.isfinite(cost) or cost < 0 or not 0 <= i < track_count
           or not 0 <= j < detection_count for cost, i, j in edges):
        raise ValueError("Invalid association edge")
    choices = [[] for _ in range(track_count)]
    for cost, i, j in sorted(edges):
        choices[i].append((j, cost))
    best_key, best = None, {}

    def visit(i, assigned, cost):
        nonlocal best_key, best
        if i == track_count:
            key = (-len(assigned), cost, tuple(sorted(assigned.items())))
            if best_key is None or key < best_key:
                best_key, best = key, dict(assigned)
            return
        visit(i + 1, assigned, cost)
        for j, value in choices[i]:
            if j not in assigned:
                assigned[j] = i
                visit(i + 1, assigned, cost + value)
                del assigned[j]

    visit(0, {}, 0.)
    return best


def assigned_ids(tracker, full, edges, assignment):
    """Preserve the baseline prohibition on births for plausible unmatched boxes."""
    ids = {j: tracker.tracks[i].track_id for j, i in assignment.items()}
    plausible, serial = {j for _, _, j in edges}, tracker.serial
    for j, _ in full:
        if j not in ids and j not in plausible:
            serial += 1
            ids[j] = f"enemy:{serial}"
    return ids


def metrics(samples, assigned, initial_ids, threshold):
    old_ids = set(initial_ids.values())
    births = {track_id for track_id in assigned.values() if track_id not in old_ids}
    return {
        "detections": len(samples),
        "confirmed_detections": sum(s.confidence >= threshold and not s.tracked for s in samples),
        "assigned": len(assigned),
        "id_switches": sum(s.actor in initial_ids and j in assigned
                           and assigned[j] != initial_ids[s.actor]
                           for j, s in enumerate(samples)),
        "correct_existing_ids": sum(s.actor in initial_ids
                                    and assigned.get(j) == initial_ids[s.actor]
                                    for j, s in enumerate(samples)),
        "unassigned_confirmed": sum(j not in assigned and s.confidence >= threshold
                                    and not s.tracked for j, s in enumerate(samples)),
        "births": len(births),
        "unsupported_births": sum(s.actor is None and assigned.get(j) in births
                                  for j, s in enumerate(samples)),
        "weak_or_predicted_assigned": sum(j in assigned
                                          and (s.confidence < threshold or s.tracked)
                                          for j, s in enumerate(samples)),
    }


def compare_case(case):
    tracker = EnemyTracker(PerceptionConfig())
    tracker.prepare(0., (0, 0), 1.)
    seeded = tracker.update([s.detection() for s in case.initial], 0.)
    initial_ids = {s.actor: d.track_id for s, d in zip(case.initial, seeded, strict=True)}
    tracker.prepare(.2, (0, 0), 1.)
    detections = [s.detection() for s in case.observations]
    full, edges, eligible = feasible_edges(tracker, detections)
    start = time.perf_counter()
    greedy = greedy_assignment(eligible)
    greedy_ms = (time.perf_counter() - start) * 1000
    mirrored = assigned_ids(tracker, full, edges, greedy)
    start = time.perf_counter()
    global_pairs = global_assignment(eligible, len(tracker.tracks), len(detections))
    global_ms = (time.perf_counter() - start) * 1000
    reference = assigned_ids(tracker, full, edges, global_pairs)
    start = time.perf_counter()
    actual = tracker.update(detections, .2)
    actual_ms = (time.perf_counter() - start) * 1000
    baseline = {j: d.track_id for j, d in enumerate(actual) if d.track_id is not None}
    if mirrored != baseline:
        raise ValueError("Mirrored association drifted from EnemyTracker.update; stop comparison")
    return {
        "case": case.name, "note": case.note,
        "baseline": metrics(case.observations, baseline, initial_ids, tracker.config.confidence),
        "reference": metrics(case.observations, reference, initial_ids, tracker.config.confidence),
        "observations": [{"actor_truth": s.actor, "x": s.x, "confidence": s.confidence,
                          "tracked": s.tracked, "baseline_id": baseline.get(j),
                          "reference_id": reference.get(j)}
                         for j, s in enumerate(case.observations)],
        "feasible_edges": edges, "eligible_after_ambiguity_veto": eligible,
        "timing_ms": {"greedy_assignment_only": greedy_ms,
                      "global_assignment_only": global_ms, "actual_tracker_update": actual_ms},
        "baseline_mirror_matches_actual": True,
    }


def experiment(repeats=50):
    if not isinstance(repeats, int) or not 1 <= repeats <= 1000:
        raise ValueError("repeats must be an integer between 1 and 1000")
    started = time.perf_counter()
    results = []
    for case in cases():
        runs = [compare_case(case) for _ in range(repeats)]
        result = runs[0]
        result["timing_ms"] = {key: {"p50": statistics.median(r["timing_ms"][key] for r in runs),
                                       "samples": repeats}
                               for key in result["timing_ms"]}
        results.append(result)
    source = Path(enemy_tracking.__file__)
    return {
        "schema": "monster-association-experiment-v1",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "input_sent": False, "evidence": "synthetic_fixed_detections",
        "scope": "One-transition cases; construction identities; no pixels or live input",
        "promotion": "deferred",
        "limitations": [
            "No detector, partial search, long occlusion or counterfactual state propagation.",
            "Global solver maximizes cardinality then cost quality, not identity certainty.",
            "Same species/distance/ambiguity/birth gates; weak scores are not relaxed.",
            "Timing excludes setup/imports; assignment-only solvers share precomputed edges.",
            "Actual tracker update includes lifecycle work, unlike solver-only timing.",
            "Constructed results cannot establish gameplay accuracy or justify promotion.",
        ],
        "cases": results, "processing_seconds": time.perf_counter() - started,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = experiment(args.repeats)
    encoded = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    print(encoded)


if __name__ == "__main__":
    main()
