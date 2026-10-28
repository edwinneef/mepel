"""Place public map data (world pixels) in a saved area's coordinates. No capture or input.

The game draws its minimap as the map's own minimap picture, one picture pixel per
2**magnification world pixels, with the world origin at the picture's (center_x,
center_y). The saved walk calibration maps the minimap marker to area pixels, so
finding where that picture sits inside the captured minimap is enough to map world
pixels to area pixels, with no taught surfaces.
"""

import base64
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from .profiles import AreaStore

# The player marker's center sits this far (minimap pixels) from the character's
# position. Measured on Middle Forest III (-1.24, -6.93) and Over the Wall
# (-0.64, -7.42) against their taught surfaces; either predicts the other within 10 px.
MARKER_BIAS = (-0.94, -7.17)
_PAD = 40  # the picture may overhang the captured canvas by this much


def picture(minimap: dict) -> np.ndarray:
    """The public minimap picture as BGRA."""
    image = cv2.imdecode(np.frombuffer(base64.b64decode(minimap["canvas"]), np.uint8),
                         cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        raise ValueError("Public minimap picture is missing or not RGBA")
    return image


def _refine(scores: np.ndarray, at: tuple[int, int]) -> tuple[float, float]:
    """Sub-pixel minimum by a parabola through each axis' neighbours."""
    result = []
    for axis in (0, 1):
        index = at[axis]
        limit = scores.shape[1 - axis]
        if not 0 < index < limit - 1:
            result.append(float(index))
            continue
        if axis == 0:
            a, b, c = scores[at[1], index - 1:index + 2]
        else:
            a, b, c = scores[index - 1:index + 2, at[0]]
        bend = a - 2 * b + c
        result.append(float(index + (0.5 * (a - c) / bend if bend > 0 else 0)))
    return result[0], result[1]


def picture_offset(captured: np.ndarray, image: np.ndarray) -> tuple[float, float]:
    """Where the public picture's top-left sits in the captured minimap canvas."""
    padded = cv2.copyMakeBorder(captured, _PAD, _PAD, _PAD, _PAD, cv2.BORDER_CONSTANT, value=0)
    if (padded.shape[0] < image.shape[0] or padded.shape[1] < image.shape[1]):
        raise ValueError("Captured minimap is far smaller than the public picture")
    mask = (image[..., 3] > 200).astype(np.float32)
    if np.count_nonzero(mask) < 200:
        raise ValueError("Public minimap picture is almost transparent")
    scores = cv2.matchTemplate(padded.astype(np.float32), image[..., :3].astype(np.float32),
                               cv2.TM_SQDIFF, mask=cv2.merge([mask] * 3))
    _, _, at, _ = cv2.minMaxLoc(scores)
    x, y = _refine(scores, at)
    return x - _PAD, y - _PAD


def world_transform(walk: dict, minimap: dict, offset: tuple[float, float]) -> dict:
    """Per axis (scale, offset) from public world pixels to area pixels.

    marker = (world + center) / 2**magnification + picture offset + marker bias,
    area = walk scale * marker + walk offset.
    """
    zoom = 2 ** minimap["magnification"]
    result = {}
    for index, axis in enumerate(("x", "y")):
        scale, shift = walk[f"scale_{axis}"], walk[f"offset_{axis}"]
        marker = minimap[f"center{axis.upper()}"] / zoom + offset[index] + MARKER_BIAS[index]
        result[axis] = (scale / zoom, scale * marker + shift)
    return result


def locate(reference: np.ndarray, canvas: dict, walk: dict, minimap: dict) -> dict:
    """World-to-area transform for one saved view, its walk calibration and a public map."""
    return world_transform(walk, minimap, picture_offset(crop(reference, canvas),
                                                         picture(minimap)))


def crop(reference: np.ndarray, canvas: dict) -> np.ndarray:
    return reference[canvas["y"]:canvas["y"] + canvas["height"],
                     canvas["x"]:canvas["x"] + canvas["width"]]


def match_score(captured: np.ndarray, image: np.ndarray) -> float:
    """Mean squared colour distance at the best placement; lower is a better map match."""
    padded = cv2.copyMakeBorder(captured, _PAD, _PAD, _PAD, _PAD, cv2.BORDER_CONSTANT, value=0)
    if padded.shape[0] < image.shape[0] or padded.shape[1] < image.shape[1]:
        return float("inf")
    mask = (image[..., 3] > 200).astype(np.float32)
    scores = cv2.matchTemplate(padded.astype(np.float32), image[..., :3].astype(np.float32),
                               cv2.TM_SQDIFF, mask=cv2.merge([mask] * 3))
    return float(scores.min() / max(1.0, 3 * np.count_nonzero(mask)))


# Layout: public world geometry to area platforms, ropes and portal zones.
ROPE_REACH_PX = 64  # a rope's foot and top reach the platform this close to its ends
PORTAL_HALF_WIDTH, PORTAL_HEIGHT = 25, 70  # visible portal footprint above its foot point


def surface(item: dict) -> list[dict]:
    return item.get("points") or [item["start"], item["end"]]


def height(item: dict, x: float) -> float:
    points = surface(item)
    return float(np.interp(x, [p["x"] for p in points], [p["y"] for p in points]))


def span(item: dict) -> tuple[float, float]:
    xs = [p["x"] for p in surface(item)]
    return min(xs), max(xs)


def _straighten(points: list[dict]) -> list[dict]:
    """Drop points on the line through their neighbours."""
    kept = [points[0]]
    for here, after in zip(points[1:], points[2:], strict=False):
        before = kept[-1]
        expected = before["y"] + (after["y"] - before["y"]) * (
            (here["x"] - before["x"]) / (after["x"] - before["x"]))
        if abs(here["y"] - expected) > 0.5:
            kept.append(here)
    return [*kept, points[-1]]


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


def pad_ends(platforms: list[dict], pad: float) -> None:
    """Extend ends by one marker step, flat; marker readings overshoot true ends by up to one.

    A pad stops at the middle of a gap to another platform at the same height.
    """
    def room(item: dict, x: float, side: int) -> float:
        gaps = []
        for other in platforms:
            edge = span(other)[0 if side > 0 else 1]
            if other is not item and abs(height(other, edge) - height(item, x)) <= 24:
                gaps.append(side * (edge - x))
        return min([pad] + [g / 2 for g in gaps if 0 <= g < 2 * pad])

    rooms = [(room(item, span(item)[0], -1), room(item, span(item)[1], 1)) for item in platforms]
    for item, (before, after) in zip(platforms, rooms, strict=True):
        left, right = span(item)
        points = surface(item)
        points = [{"x": left - before, "y": points[0]["y"]}, *points,
                  {"x": right + after, "y": points[-1]["y"]}]
        points = [{"x": round(p["x"], 1), "y": round(p["y"], 1)} for p in _straighten(points)]
        item["start"], item["end"] = points[0], points[-1]
        item.pop("points", None)
        if len(points) > 2:
            item["points"] = points


def _place(point: dict, fit: dict) -> dict:
    return {"x": fit["x"][0] * point["x"] + fit["x"][1],
            "y": fit["y"][0] * point["y"] + fit["y"][1]}


def layout(source: dict, fit: dict, step: tuple[float, float]) -> dict:
    """Named platforms, ropes, portal zones and a boundary in area pixels, with API ids.

    `step` is one minimap marker step in area pixels per axis (the walk scales).
    """
    platforms = []
    for chain in chains(source):
        points = _straighten([_place(p, fit) for p in chain["points"]])
        platform = {"id": chain["id"], "start": points[0], "end": points[-1]}
        if len(points) > 2:
            platform["points"] = points
        platforms.append(platform)
    if not platforms:
        raise ValueError("The public map has no platforms")
    pad_ends(platforms, step[0])
    ropes = []
    for index, row in enumerate(source["ladderRopes"]):
        x = round(fit["x"][0] * row["x"] + fit["x"][1], 1)
        top = fit["y"][0] * min(row["y1"], row["y2"]) + fit["y"][1]
        bottom = fit["y"][0] * max(row["y1"], row["y2"]) + fit["y"][1]
        heights = [height(p, x) for p in platforms if span(p)[0] <= x <= span(p)[1]]
        # Feet rest on the platform under a rope's foot and climb off onto the one its top
        # reaches; half a vertical marker step absorbs the marker's overshoot.
        bottom = min((y for y in heights if 0 <= y - bottom <= ROPE_REACH_PX), default=bottom)
        top = max((y for y in heights if 0 <= top - y <= ROPE_REACH_PX), default=top)
        ropes.append({"id": f"rope{index + 1}", "ladder": bool(row.get("isLadder")),
                      "start": {"x": x, "y": round(top - step[1] / 2, 1)},
                      "end": {"x": x, "y": round(bottom + step[1] / 2, 1)}})
    zones = []
    for portal in (p for p in source.get("portals", []) if p["type"] == 2):
        foot = _place(portal, fit)
        zones.append({"id": f"portal{len(zones) + 1}", "kind": "portal", "rect": {
            "x": round(foot["x"] - PORTAL_HALF_WIDTH, 1), "y": round(foot["y"] - PORTAL_HEIGHT, 1),
            "width": 2 * PORTAL_HALF_WIDTH, "height": PORTAL_HEIGHT}})
    points = [p for item in platforms + ropes for p in surface(item)]
    points += [{"x": z["rect"]["x"] + dx, "y": z["rect"]["y"] + dy} for z in zones
               for dx in (0, z["rect"]["width"]) for dy in (0, z["rect"]["height"])]
    left, top = min(p["x"] for p in points) - 40, min(p["y"] for p in points) - 100
    right, bottom = max(p["x"] for p in points) + 40, max(p["y"] for p in points) + 40
    boundary = {"x": round(left, 1), "y": round(top, 1), "width": round(right - left, 1),
                "height": round(bottom - top, 1)}
    name(platforms, ropes)
    return {"platforms": platforms, "ropes": ropes, "zones": zones, "boundary": boundary}


LEVEL_PX = 30  # platforms whose mean heights differ less than this share one level
SIDES = ("far left", "left", "center", "right", "far right")


def name(platforms: list[dict], ropes: list[dict]) -> None:
    """Plain names from position; ropes by the platform they lead up to.

    The lowest, widest platform is the Floor. The rest form levels counted up from it
    ("Level 3"); a level with several platforms adds where each sits across the map
    ("Level 3 left"); a lone highest level is the Top. Numbers appear only when two
    places would still share a name, counted left to right.
    """
    def level(item: dict) -> float:
        """The height most of the platform stands at; a trapezoid's flat top, not its feet."""
        left, right = span(item)
        return float(np.median([height(item, x) for x in np.linspace(left, right, 33)]))

    floor = max(platforms, key=lambda p: (level(p), span(p)[1] - span(p)[0]))
    left = min(span(p)[0] for p in platforms)
    across = max(max(span(p)[1] for p in platforms) - left, 1)

    def side(x: float) -> str:
        return SIDES[min(4, int(5 * (x - left) / across))]

    floor["name"] = "Floor"
    levels: list[list[dict]] = []
    for item in sorted((p for p in platforms if p is not floor), key=level, reverse=True):
        if levels and level(levels[-1][-1]) - level(item) < LEVEL_PX:
            levels[-1].append(item)
        else:
            levels.append([item])
    for number, group in enumerate(levels, 1):
        label = "Top" if number == len(levels) and len(group) == 1 else f"Level {number}"
        for item in group:
            item["name"] = (label if len(group) == 1
                            else f"{label} {side(sum(span(item)) / 2)}")
    for rope in ropes:
        x, upper = rope["start"]["x"], rope["start"]["y"]
        kind = "Ladder" if rope.pop("ladder") else "Rope"
        reach = [p for p in platforms if span(p)[0] <= x <= span(p)[1]
                 and abs(height(p, x) - upper) <= ROPE_REACH_PX]
        target = min(reach, key=lambda p: abs(height(p, x) - upper), default=None)
        rope["name"] = (f"{kind} to {target['name']}" if target
                        else f"{side(x).capitalize()} {kind.lower()}")
    for group in (platforms, ropes):
        named: dict[str, list[dict]] = {}
        for item in group:
            named.setdefault(item["name"], []).append(item)
        for same in named.values():
            if len(same) > 1:
                for number, item in enumerate(sorted(same, key=lambda i: span(i)[0]), 1):
                    item["name"] = f"{item['name']} {number}"


# Import: public map data is fetched once per map and kept beside the areas.
MAX_SOURCE_BYTES = 2_000_000
# Translucent minimaps match loosely; the right map beat the runner-up by 1.4x to 3.2x
# on the three saved areas.
IDENTIFY_MARGIN = 1.3


def cached(directory: Path, map_id: int, fetch: Callable[[str], bytes] | None = None
           ) -> tuple[dict, str]:
    """The public map and the SHA-256 of its exact bytes; fetched only when not cached."""
    if type(map_id) is not int or not 0 <= map_id <= 999_999_999:
        raise ValueError("Invalid public map ID")
    path = directory / "public" / f"{map_id}.json"
    if path.exists():
        body = path.read_bytes()
    else:
        if fetch is None:
            from .catalog import fetch_public_image as fetch
        from .catalog import API
        body = fetch(f"{API}/map/{map_id}")
        if len(body) > MAX_SOURCE_BYTES:
            raise ValueError("Public map data is too large")
        path.parent.mkdir(parents=True, exist_ok=True)
        AreaStore._atomic(path, body)
    source = json.loads(body)
    if source.get("id") != map_id or "footholds" not in source or "miniMap" not in source:
        raise ValueError(f"Public map {map_id} has no usable layout")
    return source, hashlib.sha256(body).hexdigest()


def identify(captured: np.ndarray, sources: dict[int, dict]) -> int:
    """The candidate map whose minimap picture best matches the captured minimap.

    The best match must beat the runner-up by IDENTIFY_MARGIN, or the map stays unknown.
    """
    scores = sorted((match_score(captured, picture(source["miniMap"])), map_id)
                    for map_id, source in sources.items())
    if not scores or not np.isfinite(scores[0][0]):
        raise ValueError("No candidate map matches the captured minimap")
    if len(scores) > 1 and scores[1][0] <= IDENTIFY_MARGIN * scores[0][0]:
        raise ValueError("Several maps match the captured minimap; choose the map by ID")
    return scores[0][1]


def build_area(profile: dict, reference: np.ndarray, source: dict, digest: str) -> dict:
    """A saved area with its geometry replaced by the public map. Links come from moves."""
    calibration = profile.get("minimap_calibration")
    if not calibration:
        raise ValueError("Walk-calibrate the area before importing its map")
    view = next(v for v in profile["views"] if v["id"] == calibration["view_id"])
    if not view.get("minimap"):
        raise ValueError("The calibrated view has no minimap; capture the area again")
    walk = calibration["transform"]
    fit = locate(reference, view["minimap"]["canvas"], walk, source["miniMap"])
    geometry = layout(source, fit, (walk["scale_x"], walk["scale_y"]))
    keep = ("schema_version", "id", "revision", "name", "views", "minimap_calibration")
    return {**{key: profile[key] for key in keep if key in profile}, **geometry, "links": [],
            "public_map": {"id": source["id"], "sha256": digest,
                           "world": {axis: list(fit[axis]) for axis in ("x", "y")}}}
