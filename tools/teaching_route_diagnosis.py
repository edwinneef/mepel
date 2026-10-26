"""Diagnose saved route gaps and build an offline candidate, without changing a draft."""

import argparse
import copy
import hashlib
import json
from collections import deque
from pathlib import Path

from maplebot.localization import MinimapTransform
from maplebot.map_teacher import LINK_SECONDS, MapTeacher, _Sample


def segment_key(item: dict) -> tuple:
    return tuple(item[end][axis] for end in ("start", "end") for axis in ("x", "y"))


def transitions(teacher: MapTeacher, sources: list[str], geometry: dict) -> list[dict]:
    platforms, members = teacher._platforms()
    ropes = teacher._ropes()
    stable = {segment_key(item): item["id"]
              for item in geometry["platforms"] + geometry["ropes"]}
    names = {item["id"]: stable[segment_key(item)] for item in platforms + ropes}
    result, previous = [], None
    for index, sample in enumerate(teacher.samples):
        raw = teacher._surface(sample, members, ropes)
        if raw is None:
            continue
        surface = names[raw]
        if previous and previous["surface"] != surface:
            elapsed = sample.t - previous["t"]
            same_session = previous["source"] == sources[index]
            checks = [row for row in teacher.log if previous["t"] < row["t"] <= sample.t]
            result.append({"from": previous["surface"], "to": surface,
                           "start": previous["t"], "end": sample.t, "seconds": elapsed,
                           "source": sources[index], "same_session": same_session,
                           "within_link_limit": same_session and elapsed <= LINK_SECONDS,
                           "missing_checks": sum(row.get("dot") is None for row in checks),
                           "from_feet": previous["feet"], "to_feet": sample.feet})
        previous = {"surface": surface, "t": sample.t, "feet": sample.feet,
                    "source": sources[index]}
    return result


def return_path(geometry: dict, start: str) -> list[str] | None:
    home = geometry["problems"]["home"]
    queue, seen = deque([[start]]), {start}
    while queue:
        path = queue.popleft()
        if path[-1] == home:
            return path
        for link in geometry["links"]:
            if link["from"] == path[-1] and link["to"] not in seen:
                seen.add(link["to"])
                queue.append(path + [link["to"]])
    return None


def diagnose(areas: Path, area_id: str) -> dict:
    hashes = {}

    def read(path: Path):
        content = path.read_bytes()
        hashes[str(path)] = hashlib.sha256(content).hexdigest()
        return content

    profile = json.loads(read(areas / f"{area_id}.json"))
    draft = json.loads(read(areas / "drafts" / f"{area_id}.json"))
    transform = MinimapTransform(**draft["teacher"]["transform"])
    if draft["teacher"]["transform"] != profile["minimap_calibration"]["transform"]:
        raise ValueError("Saved draft and active calibration differ; merge requires alignment")
    combined = MapTeacher(transform)
    combined.identities = copy.deepcopy(draft["teacher"]["identities"])
    combined_sources, sessions = [], []
    for path in sorted((areas / "teaching").glob(f"{area_id}-*.jsonl")):
        rows = [json.loads(line) for line in read(path).splitlines()]
        teacher = MapTeacher(transform)
        teacher.samples = [_Sample(row["t"], row["kind"], tuple(row["sample_dot"]),
                                   transform.to_area(*row["sample_dot"]))
                           for row in rows if "sample_dot" in row]
        teacher.log = [row for row in rows if "reason" in row]
        geometry = teacher.geometry()
        saved = rows[-1]["proposal"]
        # Stored endpoint coordinates establish alignment independently of labels/home metadata.
        for kind in ("platforms", "ropes"):
            if [segment_key(item) for item in geometry[kind]] != [
                    segment_key(item) for item in saved[kind]]:
                raise ValueError(f"Saved sample coordinates do not match {path}")
        source = path.name
        trace = transitions(teacher, [source] * len(teacher.samples), geometry)
        platforms, members = teacher._platforms()
        ropes = teacher._ropes()
        unassigned = [sample for sample in teacher.samples
                      if sample.kind in ("ground", "slope")
                      and teacher._surface(sample, members, ropes) is None]
        sessions.append({"source": source, "samples": len(teacher.samples),
                         "checks": len(teacher.log), "geometry": geometry,
                         "saved_problems": saved.get("problems"), "transitions": trace,
                         "unassigned_ground_samples": len(unassigned),
                         "unassigned_tail": [sample.__dict__ for sample in unassigned[-5:]],
                         "last_sample": teacher.samples[-1].__dict__})
        if combined.samples and teacher.samples[0].t - combined.samples[-1].t <= LINK_SECONDS:
            raise ValueError("Session timestamps could create a false cross-session link")
        combined.samples.extend(teacher.samples)
        combined.log.extend(teacher.log)
        combined_sources.extend([source] * len(teacher.samples))
    geometry = combined.geometry()
    trace = transitions(combined, combined_sources, geometry)
    witnesses = {(row["from"], row["to"]): row for row in reversed(trace)
                 if row["within_link_limit"]}
    if any((link["from"], link["to"]) not in witnesses for link in geometry["links"]):
        raise ValueError("Candidate contains a link without same-session timing evidence")
    targets = sessions[-1]["geometry"]["problems"]["stranded"]
    latest = sessions[-1]["geometry"]
    stable = {segment_key(item): item["id"]
              for item in geometry["platforms"] + geometry["ropes"]}
    paths = []
    for item in latest["platforms"] + latest["ropes"]:
        if item["id"] not in targets:
            continue
        key = segment_key(item)
        start = stable.get(key)
        if start is None:
            # A rope can extend when older observations cover more of the same x column.
            matches = [rope["id"] for rope in geometry["ropes"]
                       if rope["start"]["x"] == item["start"]["x"]
                       and rope["start"]["y"] <= item["start"]["y"]
                       and rope["end"]["y"] >= item["end"]["y"]]
            if len(matches) != 1:
                raise ValueError("Latest stranded surface has no unambiguous candidate match")
            start = matches[0]
        path = return_path(geometry, start)
        paths.append({"from": start, "path": path,
                      "witnesses": [witnesses[(a, b)]
                                    for a, b in zip(path, path[1:], strict=False)]
                      if path else []})
    changed = [path for path, digest in hashes.items()
               if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest]
    if changed:
        raise RuntimeError(f"Source changed during diagnosis: {changed}")
    return {"sessions": sessions, "candidate": geometry,
            "teacher_checkpoint": combined.checkpoint(), "return_paths": paths,
            "source_sha256": hashes, "input_sent": False,
            "limits": "Candidate only: changed geometry and an unreachable fragment need review. "
                      "Derived sample links do not establish physical contact or native traversal."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--areas", type=Path, default=Path("data/areas"))
    parser.add_argument("--area-id", default="98a20c69939d450fb46e5e9342b83734")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Choose a new output file")
    result = diagnose(args.areas, args.area_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"sessions": len(result["sessions"]),
                      "candidate": result["candidate"]["problems"],
                      "return_paths": [row["path"] for row in result["return_paths"]]}))


if __name__ == "__main__":
    main()
