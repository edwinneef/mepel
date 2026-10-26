"""Reversible, offline replacement of a review checkpoint; never activates a map."""

import copy
import hashlib
import json
from pathlib import Path

from .map_teacher import MapTeacher
from .profiles import AreaStore
from .teaching_drafts import TeachingDrafts, basis


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signature(value: dict) -> str:
    value = copy.deepcopy(value)
    for key in ("revision", "saved_at"):
        value.pop(key, None)
    samples = value.get("teacher", {}).get("samples", [])
    first = samples[0]["t"] if samples else 0
    for sample in samples:
        sample["t"] = round(sample["t"] - first, 5)
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _write(path: Path, value: dict) -> None:
    AreaStore._atomic(path, (json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def prepare(areas: Path, area_id: str, diagnosis: dict, backup: Path) -> dict:
    drafts = TeachingDrafts(areas, area_id)
    current = drafts.load()
    profile_path = areas / f"{area_id}.json"
    profile_hash = digest(profile_path)
    profile = json.loads(profile_path.read_text("utf-8"))
    if not current or current["phase"] != "review" or current.get("basis") != basis(profile):
        raise ValueError("A matching saved review draft is required; original preserved")
    for path, expected in diagnosis["source_sha256"].items():
        if digest(Path(path)) != expected:
            raise ValueError("Diagnosis source changed; regenerate before merging")
    checkpoint = diagnosis["teacher_checkpoint"]
    before = current["teacher"]
    def samples(value: dict) -> list:
        return json.loads(json.dumps([
            {k: v for k, v in item.items() if k != "t"} for item in value["samples"]]))
    previous, merged = samples(before), samples(checkpoint)
    if (not previous or len(merged) <= len(previous)
            or merged[-len(previous):] != previous
            or checkpoint["log"][-len(before["log"]):] != before["log"]):
        raise ValueError("Merge would omit or change current draft evidence; original preserved")
    teacher = MapTeacher.restore(checkpoint)
    geometry = teacher.geometry()
    if geometry != diagnosis["candidate"]:
        raise ValueError("Candidate does not reproduce after recovery")
    replacement = {**current, "phase": "review", "teacher": teacher.checkpoint()}
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "before.json").write_bytes(drafts.path.read_bytes())
    _write(backup / "candidate.json", geometry)
    _write(backup / "sources.json", diagnosis["source_sha256"])
    receipt = {"area_id": area_id, "areas": str(areas.resolve()),
               "profile_sha256": profile_hash, "before_sha256": digest(backup / "before.json"),
               "before_revision": current["revision"], "after_signature": signature(replacement),
               "samples": len(teacher.samples), "checks": len(teacher.log),
               "problems": geometry["problems"], "state": "prepared"}
    _write(backup / "receipt.json", receipt)
    saved = drafts.save(replacement, current["revision"])
    if digest(profile_path) != profile_hash:
        raise RuntimeError("Active map changed concurrently; backup and merged draft preserved")
    receipt.update(state="installed", after_revision=saved["revision"],
                   after_sha256=digest(drafts.path))
    _write(backup / "receipt.json", receipt)
    return receipt


def restore(backup: Path) -> dict:
    receipt = json.loads((backup / "receipt.json").read_text("utf-8"))
    areas, area_id = Path(receipt["areas"]), receipt["area_id"]
    drafts = TeachingDrafts(areas, area_id)
    current = drafts.load()
    if (receipt["state"] != "installed" or not current
            or signature(current) != receipt["after_signature"]):
        raise ValueError("Merged draft changed; preserve it and review before restoring")
    if digest(areas / f"{area_id}.json") != receipt["profile_sha256"]:
        raise ValueError("Active map changed; review before restoring")
    if digest(backup / "before.json") != receipt["before_sha256"]:
        raise ValueError("Backup changed; original and merged drafts preserved")
    original = json.loads((backup / "before.json").read_text("utf-8"))
    with (backup / "merged-before-restore.json").open("xb") as handle:
        handle.write(drafts.path.read_bytes())
    saved = drafts.save(original, current["revision"])
    receipt.update(state="restored", restored_revision=saved["revision"])
    _write(backup / "receipt.json", receipt)
    return receipt
