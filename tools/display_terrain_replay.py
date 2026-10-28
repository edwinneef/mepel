"""Replay saved recordings through the display trackers and compare with independent evidence.

Read-only: loads area profiles and recording PNGs, writes a report and drawn samples.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from maplebot.display_loop import DisplayTracks, identity
from maplebot.display_terrain import DisplayTerrain
from maplebot.geometry import Rect


def boxes(row: dict) -> tuple[Rect, ...]:
    items = [row.get("player"), *(row.get("monsters") or [])]
    return tuple(Rect(**item["box"]) for item in items if item)


def oracle(reference: np.ndarray, image: np.ndarray) -> list[float] | None:
    """Independent camera offset: exhaustive match of large reference terrain blocks."""
    offsets = []
    # Stay clear of the screen-fixed quest helper (right) and chat (bottom) in the reference.
    for top in range(190, 521, 110):
        for left in range(80, 981, 150):
            block = reference[top:top + 110, left:left + 160]
            if float(block.std()) < 25:
                continue
            scores = cv2.matchTemplate(image, block, cv2.TM_CCOEFF_NORMED)
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            if score >= 0.9:
                offsets.append((x - left, y - top))
    if len(offsets) < 3:
        return None
    offsets = np.array(offsets, float)
    median = np.median(offsets, axis=0)
    agree = np.linalg.norm(offsets - median, axis=1) <= 2
    return [float(value) for value in median] if agree.sum() >= 3 else None


def center(box: dict) -> np.ndarray:
    return np.array([box["x"] + box["width"] / 2, box["y"] + box["height"] / 2])


def box_errors(rows: list[dict], session: Path) -> dict:
    """Anchor on frame k, track into frame k+1, compare with recognition at k+1."""
    tracked, stale, matched, total = [], [], 0, 0
    for before, after in zip(rows, rows[1:], strict=False):
        if not 0 < after["captured_at"] - before["captured_at"] <= 0.5:
            continue
        tracks = DisplayTracks()
        first = cv2.imread(str(session / before["frame"]))
        tracks.anchor({"frame": {"id": before["frame"], "captured_at": before["captured_at"]},
                       **{key: before.get(key) for key in ("player", "monsters", "target")}},
                      first)
        anchors = {key: dict(track.detection) for key, track in tracks.tracks.items()}
        second = cv2.imread(str(session / after["frame"]))
        tracks.update(cv2.cvtColor(second, cv2.COLOR_BGR2GRAY), after["captured_at"])
        player, monsters, _ = tracks.items(after["captured_at"])
        shown = {item["track_id"]: item for item in ([player] if player else []) + monsters}
        observed = [after["player"]] if after.get("player") else []
        observed += after.get("monsters") or []
        for key, anchor in anchors.items():
            same = [item for item in observed if item["kind"] == anchor["kind"]
                    and (anchor["kind"] == "player" or identity(item) == identity(anchor))]
            if not same:
                continue
            truth = min(same, key=lambda item: np.linalg.norm(center(item["box"])
                                                              - center(anchor["box"])))
            if np.linalg.norm(center(truth["box"]) - center(anchor["box"])) > 120:
                continue
            total += 1
            stale.append(np.linalg.norm(center(anchor["box"]) - center(truth["box"])))
            if key in shown:
                matched += 1
                tracked.append(np.linalg.norm(center(shown[key]["box"]) - center(truth["box"])))

    def percentiles(values: list[float]) -> list[float]:
        return [round(float(np.percentile(values, q)), 1) for q in (50, 95)] if values else []

    return {"box_pairs": total, "box_tracked": matched,
            "box_error_tracked_p50_p95": percentiles(tracked),
            "box_error_stale_p50_p95": percentiles(stale)}


def draw(image: np.ndarray, area: dict, projection: dict, color: tuple[int, int, int]) -> None:
    for segment in [*area["platforms"], *area["ropes"]]:
        points = [(round(projection["x"] + point["x"] * projection["scale"]),
                   round(projection["y"] + point["y"] * projection["scale"]))
                  for point in (segment["start"], segment["end"])]
        cv2.line(image, points[0], points[1], color, 2)


def replay(session: Path, areas: Path, output: Path) -> dict:
    rows = [json.loads(line) for line in (session / "decisions.jsonl").open(encoding="utf-8")]
    rows = [row for row in rows if (session / row["frame"]).exists()]
    area_id = next(row["position"]["area_id"] for row in rows if row.get("position"))
    area = json.loads((areas / f"{area_id}.json").read_text(encoding="utf-8"))
    view = area["views"][0]
    reference = cv2.imread(str(areas / "frames" / f"{view['image']}.png"))
    tracker = DisplayTerrain()
    tracker.configure(reference, view["origin"]["x"], view["origin"]["y"], view["scale"],
                      area_id, area["revision"])
    results = []
    for row in rows:
        image = cv2.imread(str(session / row["frame"]))
        began = time.perf_counter()
        aligned = tracker.update(image, row["captured_at"], boxes(row))
        elapsed = (time.perf_counter() - began) * 1000
        position = row.get("position") or {}
        truth = position.get("projection")
        item = {
            "frame": row["frame"], "kind": position.get("kind"), "reason": position.get("reason"),
            "ms": round(elapsed, 2), "valid": aligned is not None,
        }
        if aligned:
            item["projection"] = {key: round(aligned["projection"][key], 2) for key in ("x", "y")}
            item["support"] = aligned["alignment"]["support"]
        if aligned and truth:
            item["feet_delta"] = [round(aligned["projection"]["x"] - truth["x"], 2),
                                  round(aligned["projection"]["y"] - truth["y"], 2)]
        independent = oracle(reference, image)
        if independent:
            origin = (view["origin"]["x"] * view["scale"], view["origin"]["y"] * view["scale"])
            item["oracle"] = [independent[0] - origin[0], independent[1] - origin[1]]
            if aligned:
                item["error"] = [round(aligned["projection"]["x"] - item["oracle"][0], 2),
                                 round(aligned["projection"]["y"] - item["oracle"][1], 2)]
        results.append(item)
        if output and (aligned or truth):
            drawn = image.copy()
            if truth:
                draw(drawn, area, truth, (255, 200, 120))
            if aligned:
                draw(drawn, area, aligned["projection"], (255, 120, 255))
            cv2.putText(drawn, f"{row['frame']} {position.get('kind')} {position.get('reason')}",
                        (12, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.imwrite(str(output / f"{session.name}-{row['frame']}"), drawn)
    errors = np.array([item["error"] for item in results if "error" in item]).reshape(-1, 2)
    off_platform = [item for item in results if item["kind"] != "platform"]
    registrable = [item for item in results if "oracle" in item]
    times = np.array([item["ms"] for item in results])
    summary = {
        "session": session.name, "area": area["name"], "frames": len(results),
        "valid": sum(item["valid"] for item in results),
        "off_platform": len(off_platform),
        "off_platform_valid": sum(item["valid"] for item in off_platform),
        "oracle_frames": len(registrable),
        "oracle_frames_valid": sum(item["valid"] for item in registrable),
        "compared": len(errors),
        "ms_p50": round(float(np.percentile(times, 50)), 2),
        "ms_p95": round(float(np.percentile(times, 95)), 2),
    }
    if len(errors):
        distance = np.linalg.norm(errors, axis=1)
        summary |= {"error_p50_px": round(float(np.percentile(distance, 50)), 2),
                    "error_p95_px": round(float(np.percentile(distance, 95)), 2),
                    "error_max_px": round(float(distance.max()), 2)}
    summary |= box_errors(rows, session)
    return {"summary": summary, "frames": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sessions", nargs="+", type=Path)
    parser.add_argument("--areas", type=Path, default=Path("data/areas"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/display-terrain-replay"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    reports = [replay(session, args.areas, args.output) for session in args.sessions]
    (args.output / "report.json").write_text(json.dumps(reports, indent=1), encoding="utf-8")
    print(json.dumps([report["summary"] for report in reports], indent=2))


if __name__ == "__main__":
    main()
