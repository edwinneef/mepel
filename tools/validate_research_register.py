"""Check preserved research and stable coverage IDs without importing the application."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "docs/research/maplestory-bot-ecosystem"


def link_exists(reference: str) -> None:
    name, _, anchor = reference.partition("#")
    path = DIRECTORY / name
    if not path.is_file():
        raise ValueError(f"Missing reference: {reference}")
    if anchor:
        text = path.read_text(encoding="utf-8-sig")
        slugs = {re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
                 for title in re.findall(r"^#+ (.+)$", text, re.M)}
        if anchor not in slugs:
            raise ValueError(f"Missing heading: {reference}")


def validate() -> dict:
    register = json.loads((DIRECTORY / "implementation-register.json").read_text("utf-8"))
    entries = register["entries"]
    ids = {entry["id"] for entry in entries}
    required = {*(f"B{i:02}" for i in range(1, 21)),
                *(f"X{i:02}" for i in range(1, 13)), "L01"}
    if len(ids) != len(entries) or not required <= ids:
        raise ValueError("Missing original IDs or duplicate IDs; never renumber findings")
    phases = {phase["id"] for phase in register["phases"]}
    for name, source in register["sources"].items():
        if hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Original report changed: {name}")
        if not source["coveredBy"] or not set(source["coveredBy"]) <= ids:
            raise ValueError(f"Unmapped report: {name}")
    for name, expected in register["protected"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Protected pre-existing file changed: {name}")
    for entry in entries:
        for field in ("source", "code", "phase", "dependsOn", "disposition", "acceptance",
                      "evidence", "risk", "deferral"):
            if field not in entry:
                raise ValueError(f"{entry['id']}: missing {field}")
        if not entry["acceptance"] or entry["phase"] not in phases:
            raise ValueError(f"{entry['id']}: missing acceptance or phase")
        if not set(entry["dependsOn"]) <= phases | ids:
            raise ValueError(f"{entry['id']}: unknown dependency")
        for reference in entry["source"] + entry["evidence"]:
            if isinstance(reference, str):
                link_exists(reference)
            elif not isinstance(reference, dict) or not reference.get("evidence"):
                raise ValueError(f"{entry['id']}: invalid preserved evidence record")
        for source in entry["code"]:
            if not (ROOT / source).is_file():
                raise ValueError(f"Missing code seam: {source}")
        if entry["disposition"] != "planned" and not entry["evidence"]:
            raise ValueError(f"{entry['id']}: disposition lacks evidence")
        if entry["deferral"] is not None:
            if not all(entry["deferral"].get(key) for key in ("reason", "revisit")):
                raise ValueError(f"{entry['id']}: deferral requires reason and revisit trigger")
    return {"entries": len(entries), "original_reports": len(register["sources"]),
            "phases": len(phases), "all_original_ids_present": True, "original_hashes_match": True}


if __name__ == "__main__":
    print(json.dumps(validate()))
