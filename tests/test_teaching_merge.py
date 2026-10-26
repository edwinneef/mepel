import copy
import json

import pytest
from test_live_position import AREA
from test_teaching_drafts import recording
from test_teaching_drafts import store as _store

from maplebot.live_position import LivePosition
from maplebot.map_teacher import MapTeacher
from maplebot.teaching_drafts import TeachingDrafts
from maplebot.teaching_merge import digest, prepare, restore, signature

store = _store


def candidate(store):
    position = recording(store)
    position.finish_teaching()
    position.close()
    drafts = TeachingDrafts(store.directory, AREA)
    before = drafts.load()
    checkpoint = copy.deepcopy(before["teacher"])
    teacher = MapTeacher.restore(checkpoint)
    first = checkpoint["samples"][0]
    prefix = []
    for index, x in enumerate((-80, -72, -64)):
        dot = (x, first["dot"][1] - 100)
        prefix.append({"t": first["t"] - 100 + index * .2, "kind": "ground",
                       "dot": dot, "feet": teacher.transform.to_area(*dot)})
    checkpoint["samples"] = prefix + checkpoint["samples"]
    restored = MapTeacher.restore(checkpoint)
    geometry = restored.geometry()
    checkpoint["identities"] = restored.identities
    return drafts, before, {
        "teacher_checkpoint": checkpoint, "candidate": geometry,
        "source_sha256": {str(drafts.path): digest(drafts.path)},
    }


def test_merge_is_review_only_preserves_warning_and_restores_after_restart(store, tmp_path):
    drafts, before, diagnosis = candidate(store)
    active = (store.directory / f"{AREA}.json").read_bytes()
    backup = tmp_path / "merge-backup"
    original = drafts.path.read_bytes()
    receipt = prepare(store.directory, AREA, diagnosis, backup)
    assert receipt["problems"]["unreachable"]
    assert receipt["samples"] == len(before["teacher"]["samples"]) + 3
    assert (backup / "before.json").read_bytes() == original
    position = LivePosition(store, AREA)
    assert position.proposal["problems"]["unreachable"]
    assert position.teacher is None
    assert position._teaching_status(0)["phase"] == "review"
    position.close()  # Normal recovery rebases times and writes another revision.
    restore(backup)
    assert signature(drafts.load()) == signature(before)
    assert (store.directory / f"{AREA}.json").read_bytes() == active


def test_merge_refuses_changed_diagnosis_source(store, tmp_path):
    drafts, _, diagnosis = candidate(store)
    current = drafts.load()
    drafts.save(current, current["revision"])
    previous = drafts.path.read_bytes()
    with pytest.raises(ValueError, match="source changed"):
        prepare(store.directory, AREA, diagnosis, tmp_path / "backup")
    assert drafts.path.read_bytes() == previous


def test_restore_refuses_new_user_evidence(store, tmp_path):
    drafts, _, diagnosis = candidate(store)
    backup = tmp_path / "backup"
    prepare(store.directory, AREA, diagnosis, backup)
    changed = drafts.load()
    changed["teacher"]["log"].append({"t": 999, "reason": "New evidence", "dot": None})
    drafts.save(changed, changed["revision"])
    previous = drafts.path.read_bytes()
    with pytest.raises(ValueError, match="draft changed"):
        restore(backup)
    assert drafts.path.read_bytes() == previous


def test_failed_merge_write_preserves_original_and_backup(store, tmp_path, monkeypatch):
    drafts, _, diagnosis = candidate(store)
    original = drafts.path.read_bytes()
    backup = tmp_path / "backup"
    monkeypatch.setattr(TeachingDrafts, "save", lambda *args: (_ for _ in ()).throw(
        OSError("Disk unavailable")))
    with pytest.raises(OSError, match="Disk unavailable"):
        prepare(store.directory, AREA, diagnosis, backup)
    assert drafts.path.read_bytes() == original
    assert (backup / "before.json").read_bytes() == original
    assert json.loads((backup / "receipt.json").read_text())["state"] == "prepared"
