"""Versioned, manually taught areas. Profiles contain geometry, never input authority."""

import hashlib
import json
import math
import os
import re
import shutil
import struct
import tempfile
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from .localization import MinimapTransform, ViewTransform, match_view
from .minimap_reader import describe

SCHEMA_VERSION = 2


def identifier(value: object, *, profile: bool = False) -> str:
    pattern = r"[a-f0-9]{32}" if profile else r"[A-Za-z0-9_-]{1,64}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("Invalid area or element ID")
    return value


def number(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1_000_000:
        raise ValueError("Geometry must use finite native-pixel coordinates")
    return value


def point(value: dict) -> dict:
    return {key: number(value[key]) for key in ("x", "y")}


def rectangle(value: dict) -> dict:
    result = {key: number(value[key]) for key in ("x", "y", "width", "height")}
    if min(result["width"], result["height"]) <= 0:
        raise ValueError("Area rectangles need positive width and height")
    return result


def contains(boundary: dict, p: dict) -> bool:
    return (boundary["x"] <= p["x"] <= boundary["x"] + boundary["width"]
            and boundary["y"] <= p["y"] <= boundary["y"] + boundary["height"])


def minimap(value: object, width: int, height: int) -> dict | None:
    if value is None:
        return None
    canvas = rectangle(value["canvas"])
    if not contains({"x": 0, "y": 0, "width": width, "height": height}, {
        "x": canvas["x"] + canvas["width"], "y": canvas["y"] + canvas["height"],
    }) or min(canvas["x"], canvas["y"]) < 0:
        raise ValueError("Minimap must lie inside its reference view")
    dot = value["dot"]
    if dot is not None:
        dot = point(dot)
        if not contains({"x": 0, "y": 0, "width": canvas["width"],
                         "height": canvas["height"]}, dot):
            raise ValueError("Minimap marker must lie inside the minimap")
    return {"canvas": canvas, "dot": dot}


def calibration_record(value: object) -> dict | None:
    """Walk calibration: minimap transform for one reference view, with its residual."""
    if value is None:
        return None
    view_id = identifier(value["view_id"])
    image = value["view_image"]
    if not isinstance(image, str) or not re.fullmatch(r"[a-f0-9]{64}", image):
        raise ValueError("Invalid walk-calibration view")
    transform = {key: number(value["transform"][key])
                 for key in ("scale_x", "offset_x", "scale_y", "offset_y")}
    MinimapTransform(**transform)
    residual = {axis: {key: number(value["residual_px"][axis][key])
                       for key in ("p50", "p95", "max")} for axis in ("x", "y")}
    pairs, captured_at = value["pairs"], value["captured_at"]
    if type(pairs) is not int or not 10 <= pairs <= 10_000:
        raise ValueError("Walk calibration needs 10 to 10000 pairs")
    if (type(captured_at) not in (int, float) or not math.isfinite(captured_at)
            or not 0 < captured_at < 1e11):
        raise ValueError("Invalid walk-calibration time")
    return {"view_id": view_id, "view_image": image, "transform": transform,
            "residual_px": residual, "pairs": pairs, "captured_at": captured_at}


def validate_profile(value: object) -> tuple[dict, list[str]]:
    """Validate schema 1 or 2; the result is always schema 2.

    Schema 1 views have no minimap; AreaStore derives it from the reference image.
    """
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value.get("schema_version") not in (1, SCHEMA_VERSION)):
        raise ValueError("Unsupported area schema; existing files were not changed")
    try:
        name = value["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("Give the area a name of at most 120 characters")
        revision = value["revision"]
        if type(revision) is not int or not 0 <= revision <= 1_000_000:
            raise ValueError("Invalid area revision")
        boundary = rectangle(value["boundary"])
        profile = {"schema_version": SCHEMA_VERSION, "id": identifier(value["id"], profile=True),
                   "revision": revision, "name": name.strip(), "boundary": boundary}
        ids: set[str] = set()

        def element(item: dict) -> str:
            key = identifier(item["id"])
            if key in ids:
                raise ValueError("Area element IDs must be unique")
            ids.add(key)
            return key

        for key in ("views", "zones", "platforms", "ropes", "links"):
            items = value[key]
            if not isinstance(items, list) or len(items) > (24 if key == "views" else 256):
                raise ValueError("Too many area elements")
        views = []
        for item in value["views"]:
            width, height = item["width"], item["height"]
            if any(type(n) is not int or not 1 <= n <= 16384 for n in (width, height)):
                raise ValueError("Invalid reference-view dimensions")
            origin = point(item["origin"])
            ViewTransform(origin["x"], origin["y"], item["scale"])
            image = item["image"]
            if not isinstance(image, str) or not re.fullmatch(r"[a-f0-9]{64}", image):
                raise ValueError("Invalid reference image")
            label = item.get("name", "Captured view")
            if not isinstance(label, str) or not label.strip() or len(label) > 120:
                raise ValueError("Invalid reference-view name")
            views.append({"id": element(item), "name": label.strip(), "width": width,
                          "height": height, "origin": origin, "scale": item["scale"],
                          "image": image,
                          "minimap": minimap(item.get("minimap"), width, height)})
        if not views:
            raise ValueError("Capture at least one reference view")
        profile["views"] = views
        zones = []
        for item in value["zones"]:
            box = rectangle(item["rect"])
            if item["kind"] not in {"avoid", "portal"}:
                raise ValueError("Unknown area zone kind")
            if not (contains(boundary, box) and contains(boundary, {
                "x": box["x"] + box["width"], "y": box["y"] + box["height"],
            })):
                raise ValueError("Zones must be inside the hunting boundary")
            zones.append({"id": element(item), "kind": item["kind"], "rect": box})
        profile["zones"] = zones
        nodes = []
        for kind in ("platforms", "ropes"):
            segments = []
            for item in value[kind]:
                start, end = point(item["start"]), point(item["end"])
                if start == end or not contains(boundary, start) or not contains(boundary, end):
                    raise ValueError("Nonzero platforms and ropes must be inside the boundary")
                if kind == "ropes" and abs(start["x"] - end["x"]) > 0.001:
                    raise ValueError("Ropes must be vertical")
                key = element(item)
                segment = {"id": key, "start": start, "end": end}
                if "name" in item:
                    if (not isinstance(item["name"], str) or not item["name"].strip()
                            or len(item["name"]) > 120):
                        raise ValueError("Invalid surface name")
                    segment["name"] = item["name"].strip()
                segments.append(segment)
                nodes.append(key)
            profile[kind] = segments
        links, edges = [], set()
        for item in value["links"]:
            a, b = item["from"], item["to"]
            if a == b or a not in nodes or b not in nodes:
                raise ValueError("Links need two different existing platforms or ropes")
            if (a, b) in edges:
                raise ValueError("Duplicate directed link")
            if item["kind"] not in {"walk", "jump", "climb", "drop"}:
                raise ValueError("Unknown movement-link kind")
            edges.add((a, b))
            links.append({"id": element(item), "from": a, "to": b, "kind": item["kind"]})
        profile["links"] = links
        warnings = ["Geometry only: localization, contact and movement are not verified."]
        calibration = calibration_record(value.get("minimap_calibration"))
        if calibration and not any(view["id"] == calibration["view_id"]
                                   and view["image"] == calibration["view_image"]
                                   for view in views):
            calibration = None
            warnings.append("Walk calibration removed: its reference view changed")
        if calibration:
            profile["minimap_calibration"] = calibration
        reached = set(nodes[:1])
        while True:
            extended = reached | {b for a, b in edges if a in reached}
            if extended == reached:
                break
            reached = extended
        if not nodes:
            warnings.append("No platforms or ropes have been taught")
        elif missing := set(nodes) - reached:
            warnings.append(
                "Unreachable from the first platform/rope: " + ", ".join(sorted(missing))
            )
        return profile, warnings
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Malformed area profile") from error


class AreaStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = threading.RLock()

    def _path(self, area_id: str) -> Path:
        return self.directory / f"{identifier(area_id, profile=True)}.json"

    def list(self) -> dict:
        areas, errors = [], []
        for path in sorted(self.directory.glob("*.json")):
            try:
                loaded = self.load(path.stem)["profile"]
                areas.append({key: loaded[key] for key in ("id", "name", "revision")})
            except (ValueError, OSError) as error:
                errors.append(f"{path.name}: {error}")
        return {"areas": areas, "errors": errors}

    def load(self, area_id: str) -> dict:
        with self.lock:
            path = self._path(area_id)
            try:
                if path.stat().st_size > 1_000_000:
                    raise ValueError("Area file is too large")
                value = json.loads(path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("Area file missing or unreadable; preserved unchanged") from error
            profile, warnings = validate_profile(value)
            if profile["id"] != area_id:
                raise ValueError("Area file ID does not match its name")
            upgraded = value["schema_version"] != SCHEMA_VERSION
            warnings += self._validate_views(profile, derive=upgraded)
            if upgraded:
                warnings.append("Upgraded from schema 1; saving keeps a backup of the old file")
            return {"profile": profile, "warnings": warnings}

    def _validate_views(self, profile: dict, *, derive: bool) -> "list[str]":
        """Check reference images; with derive, read each view's minimap from its pixels."""
        warnings = []
        for view in profile["views"]:
            body = self.frame(view["image"])
            if body is None or struct.unpack(">II", body[16:24]) != (view["width"], view["height"]):
                raise ValueError("Reference image is missing, corrupt or has different dimensions")
            if derive:
                image = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
                view["minimap"] = describe(image)
            if view["minimap"] is None:
                warnings.append(f"No minimap in view '{view['name']}'; open it and capture again")
        return warnings

    def save(self, value: object) -> dict:
        profile, warnings = validate_profile(value)
        with self.lock:
            # The minimap is read from the stored pixels, never taken from the client.
            warnings += self._validate_views(profile, derive=True)
            path = self._path(profile["id"])
            current = self.load(profile["id"])["profile"] if path.exists() else None
            expected = current["revision"] if current else 0
            if profile["revision"] != expected:
                raise ValueError("Area changed elsewhere; reload before saving")
            profile["revision"] = expected + 1
            body = (json.dumps(profile, indent=2, allow_nan=False) + "\n").encode()
            if len(body) > 1_000_000:
                raise ValueError("Area profile is too large")
            self.directory.mkdir(parents=True, exist_ok=True)
            if current:
                backup = path.with_suffix(f".r{expected}.{time.time_ns()}.bak")
                shutil.copy2(path, backup)
            self._atomic(path, body)
            return {"profile": profile, "warnings": warnings}

    def save_calibration(self, area_id: str, revision: int, calibration: dict) -> dict:
        """Store a walk calibration on the saved profile, with the usual backup."""
        with self.lock:
            profile = self.load(area_id)["profile"]
            if profile["revision"] != revision:
                raise ValueError("Area changed elsewhere; reload it and calibrate again")
            return self.save({**profile, "minimap_calibration": calibration})

    def save_geometry(self, area_id: str, revision: int, geometry: dict) -> dict:
        """Replace platforms, ropes, links and boundary with walked geometry; keep a backup."""
        with self.lock:
            profile = self.load(area_id)["profile"]
            if profile["revision"] != revision:
                raise ValueError("Area changed elsewhere; teach the map again")
            boundary = rectangle(geometry["boundary"])
            zones = [zone for zone in profile["zones"] if contains(boundary, zone["rect"])
                     and contains(boundary, {"x": zone["rect"]["x"] + zone["rect"]["width"],
                                             "y": zone["rect"]["y"] + zone["rect"]["height"]})]
            saved = self.save({**profile, "boundary": boundary, "zones": zones,
                               **{key: geometry[key] for key in ("platforms", "ropes", "links")}})
            if len(zones) < len(profile["zones"]):
                saved["warnings"].append("Zones outside the walked area were removed")
            return saved

    @staticmethod
    def _atomic(path: Path, body: bytes) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".area-", delete=False) as f:
                temporary = Path(f.name)
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def capture_view(self, image) -> dict:
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise ValueError("Could not save reference screenshot")
        body = encoded.tobytes()
        if len(body) > 16_000_000:
            raise ValueError("Reference screenshot is too large")
        digest = hashlib.sha256(body).hexdigest()
        with self.lock:
            path = self.directory / "frames" / f"{digest}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                self._atomic(path, body)
            elif self.frame(digest) is None:
                raise ValueError("Existing reference screenshot is corrupt; preserved unchanged")
        return {"id": uuid.uuid4().hex, "name": "Captured view", "width": image.shape[1],
                "height": image.shape[0], "origin": {"x": 0, "y": 0}, "scale": 1,
                "image": digest, "minimap": describe(image)}

    def align_view(self, image, candidates: object) -> dict:
        """Place a new capture by matching it against existing views, newest first.

        The first view with an agreeing match gives the origin; the scale is copied.
        Without overlap the view stays at origin 0, 0 for manual alignment.
        """
        if not isinstance(candidates, list) or len(candidates) > 24:
            raise ValueError("Alignment needs a list of at most 24 reference views")
        tried = 0
        for item in reversed(candidates[-6:]):
            try:
                view_id = identifier(item["id"])
                origin = point(item["origin"])
                source = ViewTransform(origin["x"], origin["y"], item["scale"])
            except (KeyError, TypeError) as error:
                raise ValueError("Malformed alignment view") from error
            body = self.frame(item["image"])
            reference = (cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
                         if body else None)
            if reference is None or reference.shape != image.shape:
                continue
            tried += 1
            match = match_view(reference, image)
            if match.offset is not None:
                x, y = source.to_area(*match.offset)
                return {"aligned": True, "view_id": view_id, "origin": {"x": x, "y": y},
                        "scale": item["scale"], "agree": match.agree, "patches": match.patches,
                        "reason": f"{match.agree} of {match.patches} textured patches agree"}
        reason = ("No overlap with a captured view; set the origin manually" if tried
                  else "No earlier view to align with")
        return {"aligned": False, "view_id": None, "origin": None, "scale": None,
                "agree": 0, "patches": 0, "reason": reason}

    def frame(self, image_id: str) -> bytes | None:
        if not isinstance(image_id, str) or not re.fullmatch(r"[a-f0-9]{64}", image_id):
            return None
        path = self.directory / "frames" / f"{image_id}.png"
        try:
            if path.stat().st_size > 16_000_000:
                return None
            body = path.read_bytes()
            if (len(body) >= 24 and body.startswith(b"\x89PNG\r\n\x1a\n")
                    and hashlib.sha256(body).hexdigest() == image_id):
                return body
        except OSError:
            pass
        return None
