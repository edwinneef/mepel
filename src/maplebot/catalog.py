"""Setup-only public sprite import. Live detection reads the local PNG catalog only."""

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.request import Request, urlopen

import cv2
import numpy as np

API = "https://api.dreamms.gg/api/GMS/latest"
STARTER_IDS = (
    100100,
    100101,
    120100,
    130100,
    130101,
    210100,
    1110100,
    1110101,
    1120100,
    1210100,
    1210101,
    1210102,
)


def fetch_public_image(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "MapleExternalBot/0.1 public-reference catalog"})
    with urlopen(request, timeout=15) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("Reference response exceeds 2 MB")
    return data


def import_catalog(
    templates: Path,
    ids: Sequence[int] = STARTER_IDS,
    *,
    fetch: Callable[[str], bytes] = fetch_public_image,
) -> dict:
    """Cache stand/move images and their provenance; never request maps, stats or spawns."""
    if not ids or any(mob <= 0 for mob in ids):
        raise ValueError("Choose one or more positive monster IDs")
    root = templates / "catalog"
    cache = root / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    previous = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    entries = {entry["file"]: entry for entry in previous.get("entries", [])}
    added, warnings = 0, []
    for mob in dict.fromkeys(ids):
        try:
            name_path = cache / f"{mob}-name.json"
            raw_name = (
                name_path.read_bytes() if name_path.exists() else fetch(f"{API}/mob/{mob}/name")
            )
            name = json.loads(raw_name)["name"]
            if not isinstance(name, str) or not name.strip() or len(name) > 100:
                raise ValueError("Invalid monster name")
            if not name_path.exists():
                name_path.write_text(json.dumps({"id": mob, "name": name}), encoding="utf-8")
        except (OSError, ValueError, KeyError) as error:
            warnings.append(f"{mob}: {error}")
            continue
        for action in ("stand", "move"):
            url = f"{API}/mob/animated/{mob}/{action}?format=png"
            raw_path = cache / f"{mob}-{action}.apng"
            try:
                data = raw_path.read_bytes() if raw_path.exists() else fetch(url)
                ok, animation = cv2.imdecodeanimation(np.frombuffer(data, np.uint8), count=32)
                if not ok or not animation.frames:
                    raise ValueError("Unreadable animation")
                selected = np.linspace(
                    0, len(animation.frames) - 1, min(3, len(animation.frames)), dtype=int
                )
                usable = 0
                for index in selected:
                    image = animation.frames[int(index)]
                    if image.ndim != 3 or image.shape[2] != 4 or max(image.shape[:2]) > 512:
                        continue
                    alpha = image[:, :, 3]
                    if np.count_nonzero(alpha >= 250) < 16:
                        continue
                    x, y, width, height = cv2.boundingRect(alpha)
                    image = image[y : y + height, x : x + width]
                    if min(width, height) < 6:
                        continue
                    ok, encoded = cv2.imencode(".png", image)
                    if not ok:
                        raise ValueError("Could not encode reference frame")
                    frame = encoded.tobytes()
                    digest = hashlib.sha256(frame).hexdigest()
                    relative = f"monster/{mob}-{action}-{index}-{digest[:12]}.png"
                    path = root / relative
                    path.parent.mkdir(exist_ok=True)
                    if path.exists() and path.read_bytes() != frame:
                        raise ValueError("Reference path collision; existing image preserved")
                    if not path.exists():
                        path.write_bytes(frame)
                    entries[relative] = {
                        "id": mob,
                        "name": name,
                        "animation": action,
                        "frame": int(index),
                        "file": relative,
                        "sha256": digest,
                        "source_url": url,
                        "source_sha256": hashlib.sha256(data).hexdigest(),
                    }
                    usable += 1
                if not usable:
                    raise ValueError("No usable transparent sprite frames")
                if not raw_path.exists():
                    raw_path.write_bytes(data)
                added += usable
            except (OSError, ValueError, cv2.error) as error:
                warnings.append(f"{name}/{action}: {error}")
    if not added:
        raise ValueError("No usable enemy images imported: " + "; ".join(warnings))
    manifest = {
        "format": 1,
        "source": API,
        "attribution": "Sprites belong to Nexon; public reference images via Dream MS",
        "entries": sorted(entries.values(), key=lambda entry: entry["file"]),
    }
    content = json.dumps(manifest, indent=2)
    if not manifest_path.exists() or manifest_path.read_text("utf-8") != content:
        if manifest_path.exists():
            manifest_path.with_suffix(f".{time.time_ns()}.bak").write_bytes(
                manifest_path.read_bytes()
            )
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(manifest_path)
    return {
        "species": len({entry["id"] for entry in entries.values()}),
        "frames": len(entries),
        "manifest": str(manifest_path),
        "warnings": warnings,
    }
