"""Normalize an explicitly supplied Classic terrain export; no network or input."""

import hashlib
import json
import math
from pathlib import Path

from .profiles import AreaStore
from .public_map import MAX_SOURCE_BYTES, picture


def cache_export(directory: Path, path: Path, digest: str) -> None:
    """Retain the exact export in a separate content-addressed provider cache."""
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("MeowDB export changed during import")
    target = directory / "public" / "meowdb-classic" / f"{digest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != body:
            raise ValueError("Cached MeowDB export changed")
    else:
        AreaStore._atomic(target, body)


def cached_source(directory: Path, public: dict) -> tuple[dict, str]:
    path = directory / "public" / "meowdb-classic" / f"{public['sha256']}.json"
    if not path.exists():
        raise ValueError("Cache the MeowDB export before starting position tracking")
    source, digest = load_source(path, public["id"])
    if digest != public["sha256"]:
        raise ValueError("Cached MeowDB export changed; import the map again")
    return source, digest


def load_source(path: Path, map_id: int | None = None) -> tuple[dict, str]:
    body = path.read_bytes()
    if len(body) > MAX_SOURCE_BYTES:
        raise ValueError("MeowDB export is too large")
    source = normalize(json.loads(body))
    if map_id is not None and source["id"] != map_id:
        raise ValueError("MeowDB export map ID differs from --map-id")
    return source, hashlib.sha256(body).hexdigest()


def normalize(bundle: dict) -> dict:
    """Join only unambiguous touching floor endpoints; compact exports omit WZ links.

    Keep walls separate and never bridge a gap or join a branching endpoint.
    The minimap must be the original-size image, with explicit WZ origin and zoom.
    """
    map_id = bundle["id"]
    if type(map_id) is not int or not 0 <= map_id <= 999_999_999:
        raise ValueError("Invalid MeowDB map ID")
    terrain, minimap = bundle["terrain"], bundle["miniMap"]
    if terrain.get("version") != 2:
        raise ValueError("Unsupported MeowDB terrain version")
    if terrain.get("ct") or terrain.get("nd"):
        raise ValueError("MeowDB terrain has unsupported collision modifiers")
    if type(minimap["magnification"]) is not int or not 0 <= minimap["magnification"] <= 8:
        raise ValueError("Invalid minimap magnification")
    image = picture(minimap)
    left, top, right, bottom = terrain["vr"]
    zoom = 2 ** minimap["magnification"]
    if (minimap["centerX"] != -left or minimap["centerY"] != -top
            or abs(image.shape[1] - (right - left) / zoom) > 1
            or abs(image.shape[0] - (bottom - top) / zoom) > 1):
        raise ValueError("MeowDB minimap does not match the terrain bounds")
    rows = {}
    for index, values in enumerate(terrain["fh"], 1):
        if len(values) != 4 or not all(type(v) in (int, float) and math.isfinite(v)
                                       for v in values):
            raise ValueError("Invalid MeowDB foothold")
        rows[index] = dict(zip(("x1", "y1", "x2", "y2"), values, strict=True))
        rows[index].update(id=index, prev=0, next=0)
    floor = [r for r in rows.values() if r["x1"] < r["x2"]]
    for row in floor:
        after = [r for r in floor if (r["x1"], r["y1"]) == (row["x2"], row["y2"])]
        before = [r for r in floor if (r["x2"], r["y2"]) == (row["x2"], row["y2"])]
        if len(after) == len(before) == 1:
            row["next"], after[0]["prev"] = after[0]["id"], row["id"]
    ropes = []
    for values in terrain["lr"]:
        if (len(values) != 4 or not all(type(v) in (int, float) and math.isfinite(v)
                                      for v in values) or values[3] not in (0, 1)
                or values[1] >= values[2]):
            raise ValueError("Invalid MeowDB ladder/rope")
        x, y1, y2, ladder = values
        ropes.append({"x": x, "y1": y1, "y2": y2, "isLadder": bool(ladder)})
    return {"id": map_id, "name": bundle.get("name"), "footholds": rows,
            "ladderRopes": ropes, "miniMap": minimap, "portals": bundle["portals"],
            "provider": "meowdb-classic"}
