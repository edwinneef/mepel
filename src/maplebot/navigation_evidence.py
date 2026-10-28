"""Read archived teaching evidence without changing profiles or retired checkpoints."""

import copy
import json
from pathlib import Path

from .localization import MinimapTransform
from .map_teacher import MapTeacher, _Sample
from .navigation import map_hash


def _key(item: dict) -> tuple:
    return tuple(item[end][axis] for end in ("start", "end") for axis in ("x", "y"))


def build_evidence(profile: dict, directory: Path) -> dict:
    expected = {key: profile[key] for key in ("platforms", "ropes", "links", "boundary")}
    teacher = None
    paths = sorted((directory / "drafts").glob(f"{profile['id']}.*.bak"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    paths += [directory / "drafts" / f"{profile['id']}.json"]
    for path in paths:
        try:
            saved = json.loads(path.read_text("utf-8"))
            checkpoint = saved.get("teacher")
            if not checkpoint or path.stat().st_size > 16_000_000:
                continue
            candidate = MapTeacher.restore(checkpoint)
            if checkpoint["transform"] != profile["minimap_calibration"]["transform"]:
                continue
            geometry = candidate.geometry()
            if {key: geometry[key] for key in expected} == expected:
                teacher = candidate
                break
        except (OSError, ValueError, TypeError, KeyError):
            continue
    manifest = {"area_id": profile["id"], "revision": profile["revision"],
                "map_hash": map_hash(profile), "edges": {}}
    if teacher is None:
        return manifest
    # Match the complete saved sequence before trusting original log timestamps. A merged
    # draft spans every log; a newer single session (or its last finish) matches one log.
    transform = MinimapTransform(**profile["minimap_calibration"]["transform"])
    sessions = []
    for path in sorted((directory / "teaching").glob(f"{profile['id']}-*.jsonl")):
        if path.stat().st_size > 16_000_000:
            continue
        rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        session = [row for row in rows if "sample_dot" in row]
        sessions.append(([_Sample(row["t"], row["kind"], tuple(row["sample_dot"]),
                                  transform.to_area(*row["sample_dot"])) for row in session],
                         [row for row in rows if "reason" in row], [path.name] * len(session)))
    wanted = [(s.kind, s.dot, s.feet) for s in teacher.samples]
    candidates = [tuple(sum((item[i] for item in sessions), []) for i in range(3)),
                  *reversed(sessions)]
    match = next((item for item in candidates
                  if [(s.kind, s.dot, s.feet) for s in item[0]] == wanted), None)
    if match is None:
        return manifest
    samples, log, sources = match
    teacher.samples, teacher.log = samples, log
    teacher.identities = copy.deepcopy(teacher.identities)
    platforms, members = teacher._platforms()
    ropes = teacher._ropes()
    stable = {_key(p): p["id"] for p in profile["platforms"] + profile["ropes"]}
    names = {p["id"]: stable[_key(p)] for p in platforms + ropes}
    previous = None
    for i, sample in enumerate(samples):
        raw = teacher._surface(sample, members, ropes)
        if raw is None:
            continue
        surface = names[raw]
        if previous and previous[0] != surface:
            origin, start = previous
            if sources[start] == sources[i] and 0 < sample.t - samples[start].t <= 6:
                between = [row for row in log if samples[start].t < row["t"] <= sample.t]
                # Each sample has a check at its own time; without one (e.g. a log left on an
                # older clock) the move's misses cannot be counted, so it proves nothing.
                if not any(row["t"] == sample.t for row in between):
                    previous = (surface, i)
                    continue
                points = samples[start:i + 1]
                times = sorted({s.t for s in points}
                               | {r["t"] for r in between if r.get("dot") is not None})
                for link in profile["links"]:
                    if (link["from"], link["to"]) != (origin, surface):
                        continue
                    row = {"from": origin, "to": surface, "kind": link["kind"],
                           "source": sources[i], "missing_checks": sum(
                               r.get("dot") is None for r in between),
                           # Continuity counts every readable check, not only the sparse
                           # samples kept during falls and climbs; misses are counted above.
                           "max_gap": max(b - a for a, b in zip(times, times[1:], strict=False)),
                           "trace": [list(s.feet) for s in points]}
                    prior = manifest["edges"].get(link["id"])
                    if prior is None or (row["missing_checks"], row["max_gap"]) < (
                            prior["missing_checks"], prior["max_gap"]):
                        manifest["edges"][link["id"]] = row
        previous = (surface, i)
    return manifest
