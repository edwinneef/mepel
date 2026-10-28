"""Setup-only: replace a saved area's geometry with its public map. Run with the engine stopped.

The saved reference view and walk calibration stay; platforms, ropes, portal zones and the
boundary come from the public map, and the previous revision is backed up by AreaStore.
"""

import json
import socket
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from .map_filter import normalize
from .profiles import AreaStore, validate_profile
from .public_map import build_area, cached, crop, identify


def engine_running(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def candidates(catalog: Path, title: str) -> list[int]:
    """Catalog maps whose title matches the area's name, best (exact) matches first."""
    if not catalog.exists():
        return []
    maps = json.loads(catalog.read_text("utf-8"))
    wanted = normalize(title)
    exact = [m["id"] for m in maps if normalize(m.get("name", "")) == wanted]
    return exact or [m["id"] for m in maps if wanted and wanted in normalize(m.get("name", ""))]


def import_map(store: AreaStore, area: str, catalog: Path, *, map_id: int | None = None,
               dry_run: bool = False, fetch: Callable[[str], bytes] | None = None) -> dict:
    match = next((item for item in store.list()["areas"] if area in (item["id"], item["name"])),
                 None)
    profile = store.load(match["id"] if match else area)["profile"]
    calibration = profile.get("minimap_calibration")
    if not calibration:
        raise ValueError("Walk-calibrate the area before importing its map")
    view = next(v for v in profile["views"] if v["id"] == calibration["view_id"])
    reference = cv2.imdecode(np.frombuffer(store.frame(view["image"]) or b"", np.uint8),
                             cv2.IMREAD_COLOR)
    if reference is None or not view.get("minimap"):
        raise ValueError("The calibrated reference view or its minimap is missing")
    ids = [map_id] if map_id is not None else candidates(catalog, profile["name"])
    if not ids:
        raise ValueError(f"No public map is named like '{profile['name']}'; pass --map-id")
    sources = {key: cached(store.directory, key, fetch) for key in ids}
    chosen = ids[0] if len(ids) == 1 else identify(
        crop(reference, view["minimap"]["canvas"]), {k: v[0] for k, v in sources.items()})
    source, digest = sources[chosen]
    candidate = build_area(profile, reference, source, digest)
    validate_profile(candidate)
    result = {"area_id": profile["id"], "area": profile["name"], "map_id": chosen,
              "public_name": source.get("name"), "platforms": len(candidate["platforms"]),
              "ropes": len(candidate["ropes"]), "zones": len(candidate["zones"]),
              "names": [item["name"] for item in candidate["platforms"] + candidate["ropes"]],
              "dry_run": dry_run, "previous_revision": profile["revision"]}
    if not dry_run:
        result["revision"] = store.save(candidate)["profile"]["revision"]
    return result
