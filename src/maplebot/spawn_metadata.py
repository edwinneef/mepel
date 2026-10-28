"""Validated population references, independent of sprite providers and their IDs."""

import json
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


def load_dataset(path: Path) -> dict:
    """Read a complete revision without modifying any sprite or cache files."""
    data = json.loads(path.read_text("utf-8"))
    validate_dataset(data)
    return data


def validate_dataset(data: dict) -> None:
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise ValueError("Unsupported spawn metadata schema")
    for key in ("sourceId", "revision"):
        if not isinstance(data.get(key), str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", data[key]):
            raise ValueError(f"Invalid {key}")
    provenance = data.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("Invalid provenance")
    url = urlparse(provenance.get("url", ""))
    if url.scheme != "https" or not url.netloc:
        raise ValueError("Provenance requires an HTTPS URL")
    if not re.fullmatch(r"[a-f0-9]{64}", str(provenance.get("sha256", ""))):
        raise ValueError("Provenance requires a SHA256")
    try:
        date.fromisoformat(provenance.get("asOf", ""))
    except (ValueError, TypeError) as error:
        raise ValueError("Provenance requires an asOf date") from error
    species = data.get("species")
    if not isinstance(species, dict) or not species:
        raise ValueError("Missing canonical species crosswalk")
    source_ids, names = set(), set()
    for key, mapping in species.items():
        if not isinstance(key, str) or not key or not isinstance(mapping, dict):
            raise ValueError("Invalid canonical species")
        source_id = mapping.get("sourceSpeciesId")
        sprite_name = mapping.get("spriteName")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("Species IDs must be nonempty strings")
        if not isinstance(sprite_name, str) or not sprite_name:
            raise ValueError("Missing explicit sprite-name mapping")
        if source_id in source_ids or sprite_name in names:
            raise ValueError("Conflicting species mapping")
        source_ids.add(source_id)
        names.add(sprite_name)
    maps = data.get("maps")
    if not isinstance(maps, list) or not maps:
        raise ValueError("Missing map records")
    identities = set()
    for record in maps:
        if not isinstance(record, dict):
            raise ValueError("Invalid map record")
        identity = record.get("mapId")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("Invalid or duplicate map identity")
        identities.add(identity)
        if any(not isinstance(record.get(k), str) or not record[k] for k in ("street", "title")):
            raise ValueError("Missing map title")
        keys = record.get("species")
        if not isinstance(keys, list) or not keys or any(
            not isinstance(key, str) or key not in species for key in keys
        ):
            raise ValueError("Unknown or missing map species")
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate map species")


def resolve_species(data: dict, entries: list[dict]) -> tuple[dict[str, set[int]], list[str]]:
    """Resolve exact reviewed names to every installed variant ID; never infer IDs."""
    validate_dataset(data)
    groups = {}
    missing = []
    for key, mapping in data["species"].items():
        ids = {entry["id"] for entry in entries if entry.get("name") == mapping["spriteName"]}
        groups[key] = ids
        if not ids:
            missing.append(key)
    return groups, missing


def import_dataset(root: Path, source: Path, *, dry_run: bool = False) -> dict:
    """Install an immutable, explicitly supplied revision in its own namespace."""
    data = load_dataset(source)
    target = root / data["sourceId"] / f"{data['revision']}.json"
    content = (json.dumps(data, indent=2) + "\n").encode("utf-8")
    if target.exists() and load_dataset(target) != data:
        raise ValueError("Revision already exists with different contents; use a new revision")
    changed = not target.exists()
    if changed and not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".{time.time_ns()}.tmp")
        temporary.write_bytes(content)
        temporary.replace(target)
    return {"path": str(target), "source": data["sourceId"], "revision": data["revision"],
            "maps": len(data["maps"]), "changed": changed, "dry_run": dry_run}
