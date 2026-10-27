"""Reproduce the Over the Wall screenshot draft in a new artifact directory only."""

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

import cv2

from maplebot.decision import PolicyInput
from maplebot.live_position import platforms
from maplebot.localization import MinimapTracker, MinimapTransform, ViewTransform, match_view
from maplebot.map_teacher import problems
from maplebot.minimap_reader import AreaMinimap
from maplebot.profiles import validate_profile

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "docs/drafts/over-the-wall-middle-ledge.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def source(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    require(path.is_relative_to(ROOT), "Source must stay inside this checkout")
    return path


def save(output: Path, name: str, value: object) -> None:
    with (output / name).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def inspect(recipe: dict, profile: dict, reader: AreaMinimap) -> list[dict]:
    reference = cv2.imread(str(source(recipe["reference"]["path"])))
    transform = MinimapTransform(**profile["minimap_calibration"]["transform"])
    view = profile["views"][0]
    mapping = ViewTransform(view["origin"]["x"], view["origin"]["y"], view["scale"])
    require(view["image"] == recipe["reference"]["sha256"], "Calibration reference changed")
    results = []
    for witness in recipe["witnesses"]:
        path = source(witness["path"])
        image = cv2.imread(str(path))
        match = match_view(reference, image)
        fix = reader.read(image)
        require(match.offset is not None and all(
            abs(a - b) <= 2 for a, b in zip(match.offset, witness["expected_offset"], strict=True)
        ), "Witness registration changed")
        require(fix.dot is not None and list(fix.dot) == witness["expected_marker"],
                "Witness marker changed")
        row = next(json.loads(line) for line in (path.parent / "decisions.jsonl")
                   .read_text("utf-8").splitlines()
                   if json.loads(line)["sequence"] == witness["sequence"])
        require(row["frame"] == path.name, "Witness log points to a different frame")
        player = PolicyInput.from_dict(row["policy_input"]).observation.player
        require(player is not None and not player.tracked and player.confidence >= .9,
                "Witness needs a fresh player detection")
        registered = mapping.to_area(player.box.center[0] + match.offset[0],
                                     player.box.feet + match.offset[1])
        area = transform.to_area(*fix.dot)
        error = [round(a - b, 3) for a, b in zip(registered, area, strict=True)]
        require(max(map(abs, error)) <= 12, "Witness disagrees with saved calibration")
        results.append({"path": witness["path"], "offset": match.offset,
                        "agreeing_patches": match.agree, "textured_patches": match.patches,
                        "marker": fix.dot, "calibrated_feet": area,
                        "registered_logged_feet": registered, "difference_px": error})
    return results


def replay(profile: dict, candidate: dict, reader: AreaMinimap, manifest: dict) -> dict:
    transform = MinimapTransform(**profile["minimap_calibration"]["transform"])
    distinct, cache, occurrences, missing = {}, {}, 0, 0
    for relative in sorted(manifest):
        if not relative.endswith("decisions.jsonl"):
            continue
        log = source(relative)
        trackers = [MinimapTracker(transform, platforms(p)) for p in (profile, candidate)]
        seen = set()
        for line in log.read_text("utf-8").splitlines():
            row = json.loads(line)
            frame = (log.parent / row["frame"]).resolve()
            require(frame.parent == log.parent, "Invalid recording frame path")
            if not frame.is_file():
                missing += 1
                continue
            require(str(frame.relative_to(ROOT)) in manifest,
                    "Replay frame absent from retained source manifest")
            timestamp = row["captured_at"]
            if timestamp in seen:
                continue
            seen.add(timestamp)
            if frame not in cache:
                cache[frame] = reader.read(cv2.imread(str(frame)))
            fix = cache[frame]
            policy = PolicyInput.from_dict(row["policy_input"])
            observation = policy.observation
            shift = observation.camera_shift if observation.camera_confidence >= .35 else None
            before, after = [t.update(fix, observation.player, shift, policy.now)
                             for t in trackers]
            if before.kind == "platform":
                require((before.kind, before.surface_id) == (after.kind, after.surface_id),
                        "Candidate changes an existing platform match")
            if after.kind == "platform":
                require(fix.dot is not None and observation.player is not None
                        and not observation.player.tracked and observation.player.confidence >= .9,
                        "Candidate reports a platform without fresh marker/player evidence")
            if (before.kind, before.surface_id) != (after.kind, after.surface_id):
                require(before.kind == "unknown"
                        and after.surface_id == candidate["platforms"][-1]["id"],
                        "Unexpected localization change outside the added platform")
            occurrences += 1
            distinct.setdefault(timestamp, {"before": before.kind, "after": after.kind,
                                           "new_surface": after.surface_id
                                           == candidate["platforms"][-1]["id"]})
    require(bool(distinct), "No retained frames replayed")
    return {"available_frame_occurrences": occurrences, "missing_png_rows": missing,
            "distinct_captures": len(distinct),
            "before": dict(Counter(r["before"] for r in distinct.values())),
            "candidate": dict(Counter(r["after"] for r in distinct.values())),
            "new_platform_matches": sum(r["new_surface"] for r in distinct.values()),
            "existing_platform_regressions": 0,
            "method": "Current pixel minimap reader, saved calibration and logged player/camera "
                      "observations; not independent accuracy or contact evidence."}


def annotate(output: Path, recipe: dict, profile: dict, evidence: list[dict]) -> None:
    view = profile["views"][0]
    mapping = ViewTransform(view["origin"]["x"], view["origin"]["y"], view["scale"])
    start, end = [mapping.to_view(p["x"], p["y"])
                  for p in (recipe["platform"]["start"], recipe["platform"]["end"])]
    entries = [(recipe["reference"]["path"], (0, 0)),
               *((r["path"], r["offset"]) for r in evidence)]
    x, y, w, h = recipe["reference"]["inspection_crop"]
    for index, (relative, offset) in enumerate(entries):
        image = cv2.imread(str(source(relative)))
        a, b = [tuple(round(v - d) for v, d in zip(point, offset, strict=True))
                for point in (start, end)]
        cv2.line(image, a, b, (60, 255, 80), 2)
        for point in (a, b):
            cv2.line(image, (point[0], point[1] - 5), (point[0], point[1] + 5),
                     (60, 255, 80), 1)
        left, top = round(x - offset[0]), round(y - offset[1])
        crop = image[top:top + h, left:left + w]
        require(crop.shape[:2] == (h, w), "Inspection crop leaves source frame")
        ok = cv2.imwrite(str(output / f"evidence-{index}.png"),
                         cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
        require(ok, "Could not write evidence crop")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.is_relative_to(ROOT / "artifacts") and output != ROOT / "artifacts",
            "Output must be a new child directory under this checkout's artifacts/")
    require(not output.exists(), "Output already exists; preserved unchanged")
    recipe = json.loads(RECIPE.read_text("utf-8"))
    profile_path = source(f"data/areas/{recipe['area_id']}.json")
    require(digest(profile_path) == recipe["base_sha256"], "Active map basis changed")
    profile = json.loads(profile_path.read_text("utf-8"))
    require(profile["revision"] == recipe["base_revision"], "Active revision changed")
    require(recipe["status"] == "review_only" and recipe["links_added"] == [],
            "Only a review-only platform addition is supported")
    candidate = copy.deepcopy(profile)
    candidate["platforms"].append(recipe["platform"])
    validate_profile(candidate)  # Validation is pure; never use AreaStore.save here.
    require({k: v for k, v in candidate.items() if k != "platforms"}
            == {k: v for k, v in profile.items() if k != "platforms"},
            "Candidate changes more than platform coverage")
    protected = [ROOT / "config.toml", *sorted((ROOT / "data").glob("*.json")),
                 *sorted((ROOT / "data/areas").rglob("*.json"))]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in protected}
    manifest_path = source(recipe["replay_manifest"])
    manifest = json.loads(manifest_path.read_text("utf-8"))
    hashes.update(manifest)
    hashes[str(manifest_path.relative_to(ROOT))] = digest(manifest_path)
    hashes[str(RECIPE.relative_to(ROOT))] = digest(RECIPE)
    for item in [recipe["reference"], *recipe["witnesses"]]:
        hashes[item["path"]] = item["sha256"]
    require(all(digest(source(p)) == sha for p, sha in hashes.items()),
            "Retained evidence or protected file changed before replay")
    reader = AreaMinimap(cv2.imread(str(source(recipe["reference"]["path"]))))
    evidence = inspect(recipe, profile, reader)
    result = replay(profile, candidate, reader, manifest)
    require(all(digest(source(p)) == sha for p, sha in hashes.items()),
            "Source changed during replay; no draft written")
    output.mkdir(parents=True, exist_ok=False)
    with (output / "active-profile-before.json").open("xb") as handle:
        handle.write(profile_path.read_bytes())
    save(output, "candidate-profile.json", candidate)
    save(output, "source-hashes.json", hashes)
    annotate(output, recipe, profile, evidence)
    require(all(digest(source(p)) == sha for p, sha in hashes.items()),
            "Source changed while writing artifacts; preserve bundle and inspect")
    report = {"status": "review_only", "active_revision": profile["revision"],
              "active_sha256": recipe["base_sha256"], "active_map_unchanged": True,
              "protected_files": len(protected), "source_files_unchanged": True,
              "input_sent": False, "native_acceptance": False, "links_added": [],
              "platform_added": recipe["platform"], "alignment": evidence, "replay": result,
              "candidate_problems": problems(candidate["platforms"], candidate["ropes"],
                                             candidate["links"]),
              "candidate_sha256": digest(output / "candidate-profile.json"),
              "rollback": "No activation occurred. Ignore this artifact bundle to discard the "
                          "candidate; active data and teaching checkpoint were never written."}
    save(output, "report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
