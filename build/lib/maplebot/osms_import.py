"""Setup-only import of commit-pinned public OSMS population metadata."""

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from urllib.request import urlopen

from .spawn_metadata import install_dataset, resolve_species, validate_dataset

BASE = "https://raw.githubusercontent.com/ohmi69/osms_datamine_dashboard"
VERIFIED_COMMIT = "17dc5dc14cc1d1f05152362c1bbcffa068e8dc81"


def identifier(value: object) -> str:
    if type(value) is not int or not 0 <= value <= 999999999:
        raise ValueError("Invalid OSMS numeric ID")
    return str(value)


def convert(maps: dict, monsters: dict, commit: str, digest: str) -> dict:
    """Discard positions; retain only explicit map populations and exact names."""
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("OSMS requires a full lowercase commit SHA")
    species = {}
    for mob in monsters["monsters"]:
        key = identifier(mob["id"])
        if key in species or not isinstance(mob["name"], str) or not mob["name"].strip():
            raise ValueError("Duplicate or unnamed OSMS monster")
        species[key] = {"sourceSpeciesId": key, "spriteName": mob["name"].strip()}
    records = []
    skipped = []
    for region in maps["regions"]:
        for record in region["maps"]:
            identity = identifier(record["id"]).zfill(9)
            if not record.get("name") or not record.get("street_name"):
                skipped.append(identity)
                continue
            keys = sorted({identifier(mob["id"]) for mob in record.get("mob_positions", [])})
            records.append({"mapId": identity, "street": record["street_name"],
                            "title": record["name"], "species": keys})
    if len(species) != monsters["total"] or len(records) + len(skipped) != maps["total"]:
        raise ValueError("OSMS totals do not match records")
    data = {"schemaVersion": 1, "sourceId": "osms-classic", "revision": commit,
            "provenance": {"url": f"{BASE}/{commit}/data/current/maps.json",
                           "sha256": digest, "asOf": date.today().isoformat()},
            "species": species, "maps": records, "skippedUnnamedMaps": skipped}
    validate_dataset(data)
    return data


def import_osms(root: Path, entries: list[dict], commit: str = VERIFIED_COMMIT,
                *, dry_run: bool = False) -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("OSMS requires a full lowercase commit SHA")
    payloads = []
    for filename in ("maps.json", "monsters.json"):
        with urlopen(f"{BASE}/{commit}/data/current/{filename}", timeout=30) as response:
            payload = response.read(8 * 1024 * 1024 + 1)
        if len(payload) > 8 * 1024 * 1024:
            raise ValueError("OSMS file exceeds 8 MiB")
        payloads.append(payload)
    digest = hashlib.sha256(b"\0".join(payloads)).hexdigest()
    data = convert(*(json.loads(payload) for payload in payloads), commit, digest)
    # Preserve the original retrieval date when the same immutable content is reimported.
    target = root / data["sourceId"] / f"{commit}.json"
    if target.exists():
        previous = json.loads(target.read_text("utf-8"))
        data["provenance"]["asOf"] = previous["provenance"]["asOf"]
    groups, missing = resolve_species(data, entries)
    blocked = [{"mapId": m["mapId"], "title": m["title"],
                "missing": sorted({data["species"][k]["spriteName"]
                                   for k in m["species"] if not groups[k]})}
               for m in data["maps"] if any(not groups[k] for k in m["species"])]
    result = install_dataset(root, data, dry_run=dry_run)
    return {**result, "coveredMaps": len(data["maps"]) - len(blocked),
            "emptyMaps": sum(not m["species"] for m in data["maps"]),
            "missingSpecies": missing, "blockedMaps": blocked,
            "skippedUnnamedMaps": data["skippedUnnamedMaps"]}
