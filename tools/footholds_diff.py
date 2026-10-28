"""Compare a taught area with public map footholds and ropes. Offline; writes one report.

The public map is fetched once from the catalog API (or read from a saved copy) and
never changes `data/areas`. Taught coordinates come through the walk calibration, so
the report fits one scale and offset per axis from public world pixels to area pixels
and shows what the teacher found, missed or invented under that fit.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from maplebot.catalog import API, fetch_public_image
from maplebot.navigation import surface_y

ROPE_PX = 16  # a taught rope this close in x to a public rope is the same rope
PLATFORM_PX = 24  # mean height gap allowed for a match; the navigator's surface tolerance
MIN_OVERLAP = 0.5  # share of a taught platform's width that must lie over the public one
STEP_PX = 16  # spacing of the height samples compared along a platform


def chains(source: dict) -> list[dict]:
    """Standable foothold runs as left-to-right world polylines; walls are dropped."""
    rows = {int(key): row for key, row in source["footholds"].items()}
    floor = {key for key, row in rows.items() if row["x1"] < row["x2"]}
    links: dict[int, set[int]] = {key: set() for key in floor}
    for key in floor:
        for other in (rows[key]["next"], rows[key]["prev"]):
            if other in floor:
                links[key].add(other)
                links[other].add(key)
    result, seen = [], set()
    for key in sorted(floor):
        if key in seen:
            continue
        group, todo = [], [key]
        seen.add(key)
        while todo:
            item = todo.pop()
            group.append(rows[item])
            for other in links[item] - seen:
                seen.add(other)
                todo.append(other)
        points = sorted({(r["x1"], r["y1"]) for r in group} | {(r["x2"], r["y2"]) for r in group})
        result.append({"id": f"fh{min(r['id'] for r in group)}",
                       "points": [{"x": x, "y": y} for x, y in points]})
    return sorted(result, key=lambda c: (c["points"][0]["y"], c["points"][0]["x"]))


def public_ropes(source: dict) -> list[dict]:
    return [{"id": f"rope{index + 1}", "x": row["x"], "top": min(row["y1"], row["y2"]),
             "bottom": max(row["y1"], row["y2"]), "ladder": bool(row.get("isLadder"))}
            for index, row in enumerate(source["ladderRopes"])]


def _height(points: list[dict], x: float) -> float | None:
    xs = [p["x"] for p in points]
    if not xs[0] <= x <= xs[-1]:
        return None
    return float(np.interp(x, xs, [p["y"] for p in points]))


def _xs(platform: dict) -> tuple[float, float]:
    points = platform.get("points") or [platform["start"], platform["end"]]
    return min(p["x"] for p in points), max(p["x"] for p in points)


def _place(chain: dict, fit: dict) -> list[dict]:
    return [{"x": fit["x"][0] * p["x"] + fit["x"][1], "y": fit["y"][0] * p["y"] + fit["y"][1]}
            for p in chain["points"]]


def match_platform(taught: dict, placed: dict[str, list[dict]]) -> dict | None:
    left, right = _xs(taught)
    best = None
    for key, points in placed.items():
        lo, hi = max(left, points[0]["x"]), min(right, points[-1]["x"])
        if hi - lo < MIN_OVERLAP * max(right - left, 1):
            continue
        gaps = [abs(surface_y(taught, x) - _height(points, x))
                for x in np.append(np.arange(lo, hi, STEP_PX), hi)]
        mean = float(np.mean(gaps))
        if mean <= PLATFORM_PX and (best is None or mean < best["mean_dy"]):
            best = {"public": key, "mean_dy": round(mean, 1), "max_dy": round(max(gaps), 1),
                    "overlap": [round(lo, 1), round(hi, 1)]}
    return best


def match_merged(taught: dict, placed: dict[str, list[dict]]) -> dict | None:
    """Two or more public platforms at the taught height that one taught platform spans."""
    left, right = _xs(taught)
    parts = []
    for key, points in placed.items():
        lo, hi = max(left, points[0]["x"]), min(right, points[-1]["x"])
        if hi - lo < STEP_PX:
            continue
        gaps = [abs(surface_y(taught, x) - _height(points, x))
                for x in np.append(np.arange(lo, hi, STEP_PX), hi)]
        if np.mean(gaps) <= PLATFORM_PX:
            parts.append((points[0]["x"], points[-1]["x"], key))
    parts.sort()
    if (len(parts) < 2
            or sum(hi - lo for lo, hi, _ in parts) < MIN_OVERLAP * max(right - left, 1)):
        return None
    return {"public": [key for _, _, key in parts],
            "gaps_px": [round(b[0] - a[1], 1) for a, b in zip(parts, parts[1:], strict=False)]}


def match_rope(taught: dict, ropes: list[dict], fit: dict) -> dict | None:
    x = taught["start"]["x"]
    best = None
    for rope in ropes:
        dx = fit["x"][0] * rope["x"] + fit["x"][1] - x
        top, bottom = (fit["y"][0] * rope[k] + fit["y"][1] for k in ("top", "bottom"))
        overlaps = taught["start"]["y"] <= bottom + ROPE_PX and top - ROPE_PX <= taught["end"]["y"]
        if abs(dx) <= ROPE_PX and overlaps and (best is None or abs(dx) < abs(best["dx"])):
            best = {"public": rope["id"], "dx": round(dx, 1),
                    "public_extent": [round(top, 1), round(bottom, 1)],
                    "taught_extent": [taught["start"]["y"], taught["end"]["y"]]}
    return best


def _pairs(profile: dict, chains_: list[dict], ropes: list[dict], fit: dict) -> tuple:
    """World/area pairs that support the fit: rope x, and heights along matched platforms."""
    xs, ys = [], []
    for taught in profile["ropes"]:
        hit = match_rope(taught, ropes, fit)
        if hit:
            rope = next(r for r in ropes if r["id"] == hit["public"])
            xs.append((rope["x"], taught["start"]["x"]))
    placed = {c["id"]: _place(c, fit) for c in chains_}
    worlds = {c["id"]: c["points"] for c in chains_}
    for taught in profile["platforms"]:
        hit = match_platform(taught, placed)
        if not hit:
            continue
        lo, hi = hit["overlap"]
        for x in np.append(np.arange(lo, hi, STEP_PX), hi):
            world_x = (x - fit["x"][1]) / fit["x"][0]
            world_y = _height(worlds[hit["public"]], world_x)
            if world_y is not None:
                ys.append((world_y, surface_y(taught, x)))
    return xs, ys


def _score(profile: dict, chains_: list[dict], ropes: list[dict], fit: dict) -> int:
    placed = {c["id"]: _place(c, fit) for c in chains_}
    return (sum(match_rope(t, ropes, fit) is not None for t in profile["ropes"])
            + sum(match_platform(t, placed) is not None for t in profile["platforms"]))


def fit_axes(profile: dict, chains_: list[dict], ropes: list[dict], k: tuple) -> dict:
    """Search offsets at the walk-implied scale, then refine scale and offset by least squares.

    Rope x proposes x offsets; platform heights propose y offsets. The pair that matches
    the most taught surfaces wins, which keeps one wrong correspondence from steering the fit.
    """
    xs = {round(t["start"]["x"] - k[0] * r["x"]) for t in profile["ropes"] for r in ropes}
    if xs:
        # Rope x alone settles the x offset; only the best ones go on to the height search.
        def aligned(bx: int) -> int:
            return sum(any(abs(k[0] * r["x"] + bx - t["start"]["x"]) <= ROPE_PX for r in ropes)
                       for t in profile["ropes"])
        top = max(aligned(bx) for bx in xs)
        xs = {bx for bx in xs if aligned(bx) == top}
    else:
        xs = {round(_xs(t)[0] - k[0] * c["points"][0]["x"])
              for t in profile["platforms"] for c in chains_}
    ys = {round(t["start"]["y"] - k[1] * c["points"][0]["y"])
          for t in profile["platforms"] for c in chains_}
    best, best_score = None, -1
    for bx in sorted(xs):
        for by in sorted(ys):
            fit = {"x": (k[0], bx), "y": (k[1], by)}
            score = _score(profile, chains_, ropes, fit)
            if score > best_score:
                best, best_score = fit, score
    if best is None:
        raise ValueError("Nothing to compare: the area or public map has no surfaces")
    for _ in range(3):
        x_pairs, y_pairs = _pairs(profile, chains_, ropes, best)
        refined = dict(best)
        if len({w for w, _ in x_pairs}) >= 2:
            refined["x"] = tuple(float(v) for v in np.polyfit(*zip(*x_pairs, strict=True), 1))
        if len({w for w, _ in y_pairs}) >= 2:
            refined["y"] = tuple(float(v) for v in np.polyfit(*zip(*y_pairs, strict=True), 1))
        if _score(profile, chains_, ropes, refined) < best_score:
            break
        best = refined
    return best


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    values = np.abs(np.array(values, float))
    return {"n": len(values), "p50": round(float(np.percentile(values, 50)), 1),
            "p95": round(float(np.percentile(values, 95)), 1),
            "max": round(float(values.max()), 1)}


def compare(profile: dict, source: dict) -> dict:
    chains_, ropes = chains(source), public_ropes(source)
    transform = profile["minimap_calibration"]["transform"]
    zoom = 2 ** source["miniMap"]["magnification"]
    k = (transform["scale_x"] / zoom, transform["scale_y"] / zoom)
    fit = fit_axes(profile, chains_, ropes, k)
    placed = {c["id"]: _place(c, fit) for c in chains_}
    names = {item["id"]: item.get("name", item["id"])
             for item in profile["platforms"] + profile["ropes"]}

    platforms, spans, extra, used = [], [], [], {}
    for taught in profile["platforms"]:
        hit = match_platform(taught, placed)
        if hit:
            platforms.append({"taught": taught["id"], "name": names[taught["id"]], **hit})
            used.setdefault(hit["public"], []).append(_xs(taught))
            continue
        merged = match_merged(taught, placed)
        if merged:
            spans.append({"taught": taught["id"], "name": names[taught["id"]], **merged})
            for key in merged["public"]:
                used.setdefault(key, []).append(_xs(taught))
        else:
            left, right = _xs(taught)
            extra.append({"taught": taught["id"], "name": names[taught["id"]],
                          "x": [left, right], "y": [taught["start"]["y"], taught["end"]["y"]]})
    missing, coverage = [], []
    for chain in chains_:
        points = placed[chain["id"]]
        span = [round(points[0]["x"], 1), round(points[-1]["x"], 1)]
        heights = [round(p["y"], 1) for p in points]
        row = {"public": chain["id"], "x": span, "y": [min(heights), max(heights)],
               "sloped": min(heights) != max(heights)}
        if chain["id"] not in used:
            missing.append(row)
            continue
        walked = sum(max(0.0, min(hi, span[1]) - max(lo, span[0]))
                     for lo, hi in used[chain["id"]])
        coverage.append({**row, "taught": len(used[chain["id"]]),
                         "walked_share": round(min(1.0, walked / max(span[1] - span[0], 1)), 2)})

    rope_rows, rope_extra, rope_used = [], [], set()
    for taught in profile["ropes"]:
        hit = match_rope(taught, ropes, fit)
        if hit:
            rope_used.add(hit["public"])
            rope_rows.append({"taught": taught["id"], "name": names[taught["id"]], **hit})
        else:
            rope_extra.append({"taught": taught["id"], "name": names[taught["id"]],
                               "x": taught["start"]["x"]})
    rope_missing = [{"public": r["id"], "ladder": r["ladder"],
                     "x": round(fit["x"][0] * r["x"] + fit["x"][1], 1),
                     "y": [round(fit["y"][0] * r[key] + fit["y"][1], 1)
                           for key in ("top", "bottom")]}
                    for r in ropes if r["id"] not in rope_used]

    x_pairs, y_pairs = _pairs(profile, chains_, ropes, fit)
    portals = [{"name": p["portalName"], "type": p["type"],
                "x": round(fit["x"][0] * p["x"] + fit["x"][1], 1),
                "y": round(fit["y"][0] * p["y"] + fit["y"][1], 1)}
               for p in source.get("portals", [])]
    taught_total = len(profile["platforms"]) + len(profile["ropes"])
    matched = len(platforms) + len(spans) + len(rope_rows)
    return {
        "transform": {
            "fitted": {axis: {"scale": round(fit[axis][0], 4), "offset": round(fit[axis][1], 1)}
                       for axis in ("x", "y")},
            "walk_implied_scale": {"x": round(k[0], 4), "y": round(k[1], 4)},
            "note": "Area pixels per public world pixel. Fitted matching walk_implied means "
                    "the taught map follows the game's minimap magnification; 1.0 would mean "
                    "area pixels equal game world pixels.",
        },
        "residual_px": {"rope_x": _stats([a - (fit["x"][0] * w + fit["x"][1])
                                          for w, a in x_pairs]),
                        "platform_y": _stats([a - (fit["y"][0] * w + fit["y"][1])
                                              for w, a in y_pairs])},
        "summary": {"taught_platforms": len(profile["platforms"]),
                    "public_platforms": len(chains_), "matched_platforms": len(platforms),
                    "taught_platforms_spanning_gaps": len(spans),
                    "extra_taught_platforms": len(extra),
                    "public_platforms_never_walked": len(missing),
                    "taught_ropes": len(profile["ropes"]), "public_ropes": len(ropes),
                    "matched_ropes": len(rope_rows), "public_ropes_never_climbed":
                    len(rope_missing), "taught_surfaces_matched": round(matched / taught_total, 2)
                    if taught_total else None},
        "platforms": {"matched": platforms, "spanning_gaps": spans, "public_coverage": coverage,
                      "extra_taught": extra, "public_never_walked": missing},
        "ropes": {"matched": rope_rows, "extra_taught": rope_extra,
                  "public_never_climbed": rope_missing},
        "portals": portals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", type=Path,
                        default=Path("data/areas/362bc0749cdc41efb045ecc06b483633.json"))
    parser.add_argument("--map-id", type=int, default=103030200)
    parser.add_argument("--source", type=Path, help="saved public map JSON; skips the fetch")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to replace {args.output}")
    area_bytes = args.area.read_bytes()
    if args.source:
        payload, origin = args.source.read_bytes(), str(args.source)
    else:
        origin = f"{API}/map/{args.map_id}"
        payload = fetch_public_image(origin)
    profile, source = json.loads(area_bytes), json.loads(payload)
    if source.get("id") not in (None, args.map_id):
        raise SystemExit(f"Public map {source.get('id')} is not --map-id {args.map_id}")
    report = {"area": {"path": str(args.area), "id": profile["id"], "name": profile.get("name"),
                       "revision": profile["revision"],
                       "sha256": hashlib.sha256(area_bytes).hexdigest()},
              "public": {"origin": origin, "map_id": source.get("id", args.map_id),
                         "name": source.get("name"), "street": source.get("streetName"),
                         "sha256": hashlib.sha256(payload).hexdigest()},
              **compare(profile, source)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.source:
        # Keep the exact bytes so a rerun with --source compares the same public map.
        args.output.with_suffix(".source.json").write_bytes(payload)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({**report["summary"], **report["transform"]["fitted"],
                      "residual_px": report["residual_px"]}, indent=2))


if __name__ == "__main__":
    main()
