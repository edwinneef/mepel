"""Add missing Classic sprites without replacing existing catalog assets."""

import hashlib
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

from .catalog import fetch_public_image
from .osms_import import BASE
from .perception import TemplateDetector
from .spawn_metadata import load_dataset


def import_sprites(templates: Path, dataset: Path, *, dry_run: bool = False,
                   fetch=fetch_public_image) -> dict:
    data = load_dataset(dataset)
    commit = data["revision"]
    if data["sourceId"] != "osms-classic" or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Select a commit-pinned OSMS dataset")
    root = templates / "catalog"
    manifest_path = root / "manifest.json"
    original = manifest_path.read_bytes() if manifest_path.exists() else None
    manifest = json.loads(original) if original is not None else {"format": 1, "entries": []}
    entries = manifest["entries"]
    names = {e["name"] for e in entries}
    needed = {k for m in data["maps"] for k in m["species"]
              if data["species"][k]["spriteName"] not in names}
    if not needed:
        return {"names": [], "frames": 0, "changed": False, "dry_run": dry_run}
    base = f"{BASE}/{commit}"
    records = json.loads(fetch(f"{base}/data/current/monsters.json"))["monsters"]
    monsters = {str(m["id"]): m for m in records}
    if len(monsters) != len(records):
        raise ValueError("Duplicate OSMS monster IDs")
    additions, images, cache = [], {}, {}
    imported = set()
    for key in sorted(needed):
        mapping = data["species"][key]
        mob = monsters[mapping["sourceSpeciesId"]]
        name = mapping["spriteName"]
        if mob["name"].strip() != name or ":" in name:
            raise ValueError("OSMS sprite name differs from selected metadata")
        if name in imported:
            continue
        source_id = mapping["sourceSpeciesId"]
        if not source_id.isdecimal() or not 0 <= int(source_id) <= 999999999:
            raise ValueError("Invalid OSMS source ID")
        # Reserve negative IDs outside the source range; Dream asset IDs stay untouched.
        asset_id = -1_000_000_000 - int(source_id)
        if any(e["id"] == asset_id for e in entries):
            raise ValueError("OSMS asset ID collision")
        start = len(additions)
        for action in ("stand", "move", "fly"):
            asset = mob.get("gifs", {}).get(action)
            if asset is None:
                continue
            if not re.fullmatch(r"[a-f0-9]{16,64}", asset):
                raise ValueError("Invalid OSMS image hash")
            url = f"{base}/data/images/monsters/{asset}.webp"
            if url not in cache:
                cache[url] = fetch(url)
            raw = cache[url]
            ok, animation = cv2.imdecodeanimation(np.frombuffer(raw, np.uint8).reshape(1, -1))
            if not ok or not animation.frames:
                raise ValueError(f"Unreadable OSMS animation: {name}/{action}")
            for index, image in enumerate(animation.frames):
                if image.ndim != 3 or image.shape[2] != 4 or max(image.shape[:2]) > 512:
                    continue
                if np.count_nonzero(image[:, :, 3] >= 250) < 16:
                    continue
                x, y, width, height = cv2.boundingRect(image[:, :, 3])
                image = image[y:y + height, x:x + width]
                if min(width, height) < 6:
                    continue
                try:
                    TemplateDetector.validate(image[:, :, :3])
                except ValueError:
                    continue
                ok, encoded = cv2.imencode(".png", image)
                if not ok:
                    raise ValueError("Could not encode OSMS frame")
                content = encoded.tobytes()
                digest = hashlib.sha256(content).hexdigest()
                relative = f"monster/osms-{source_id}-{action}-{index}-{digest[:12]}.png"
                target = root / relative
                if target.exists() and target.read_bytes() != content:
                    raise ValueError("OSMS image path collision")
                images[relative] = content
                additions.append({"id": asset_id, "name": name, "animation": action,
                                  "frame": index, "file": relative, "sha256": digest,
                                  "source_url": url,
                                  "source_sha256": hashlib.sha256(raw).hexdigest(),
                                  "provider": "osms-classic", "source_id": source_id,
                                  "source_revision": commit})
        if len(additions) == start:
            raise ValueError(f"No usable OSMS frames: {name}")
        imported.add(name)
    if not dry_run:
        current = manifest_path.read_bytes() if manifest_path.exists() else None
        if current != original:
            raise ValueError("Catalog changed during import; retry from the new manifest")
        root.mkdir(parents=True, exist_ok=True)
        if original is not None:
            manifest_path.with_suffix(f".{time.time_ns()}.bak").write_bytes(original)
        for relative, content in images.items():
            target = root / relative
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                target.write_bytes(content)
        updated = {**manifest, "entries": sorted(entries + additions, key=lambda e: e["file"])}
        temporary = manifest_path.with_suffix(f".{time.time_ns()}.tmp")
        temporary.write_text(json.dumps(updated), encoding="utf-8")
        temporary.replace(manifest_path)
    return {"names": sorted(imported), "frames": len(additions), "assets": len(cache),
            "changed": bool(additions), "dry_run": dry_run}
