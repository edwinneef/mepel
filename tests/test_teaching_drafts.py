import json
import time

import pytest
from test_live_position import AREA, calibrate, step
from test_live_position import store as _store

from maplebot.live_position import LivePosition

store = _store


def recording(store):
    position = LivePosition(store, AREA)
    calibrate(position)
    position.begin_teaching()
    for index, x in enumerate(range(10, 100, 5)):
        step(position, x, time.perf_counter() + index * 0.2)
    position._checkpoint(force=True)
    return position


def test_restart_recovers_checkpoint_without_recording_or_replacing_map(store):
    position = recording(store)
    before = store.load(AREA)["profile"]
    count = len(position.teacher.samples)
    position.close()
    recovered = LivePosition(store, AREA)
    try:
        assert recovered._teaching_status(0)["phase"] == "interrupted"
        assert recovered.teacher is None
        assert len(recovered.finished.samples) == count
        assert store.load(AREA)["profile"] == before
        recovered.resume_teaching()
        assert recovered.teacher.last is None
        assert time.perf_counter() - recovered.teacher.samples[-1].t > 6
    finally:
        recovered.close()


def test_finish_review_survives_restart_and_legacy_log_can_be_recovered(store):
    position = recording(store)
    proposal = position.finish_teaching()
    position.close()
    recovered = LivePosition(store, AREA)
    assert recovered.proposal == {k: v for k, v in proposal.items() if k != "log"}
    recovered.close()
    recovered.drafts.path.unlink()  # Simulate the pre-draft version, which only wrote Finish logs.
    legacy = LivePosition(store, AREA)
    try:
        assert legacy.proposal == recovered.proposal
        assert legacy.drafts.path.exists()
        assert legacy._teaching_status(0)["draft"]["saved"] is True
    finally:
        legacy.close()


def test_failed_checkpoint_preserves_last_saved_bytes_and_reports_error(store, monkeypatch):
    position = recording(store)
    before = position.drafts.path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(position.drafts, "save", lambda *args: (_ for _ in ()).throw(
            OSError("disk unavailable")))
        position._checkpoint(force=True)
        assert position.drafts.path.read_bytes() == before
        assert "disk unavailable" in position._teaching_status(0)["draft"]["error"]
        assert position._teaching_status(0)["draft"]["saved"] is False
    position.close()


def test_changed_map_and_corrupt_draft_stay_preserved_until_explicit_discard(store):
    position = recording(store)
    position.close()
    before = position.drafts.path.read_bytes()
    store.save(store.load(AREA)["profile"])
    recovered = LivePosition(store, AREA)
    assert recovered._teaching_status(0)["phase"] == "conflict"
    recovered.close()
    assert recovered.drafts.path.read_bytes() == before
    recovered.drafts.path.write_text("{broken", encoding="utf-8")
    broken = LivePosition(store, AREA)
    assert broken._teaching_status(0)["phase"] == "conflict"
    with pytest.raises(ValueError, match="Resume or explicitly discard"):
        broken.begin_teaching()
    broken.cancel_teaching()
    assert json.loads(broken.drafts.path.read_text())["phase"] == "discarded"
    assert any(p.read_text() == "{broken" for p in broken.drafts.path.parent.glob("*.bak"))
    broken.close()


def test_stale_draft_writer_cannot_replace_a_newer_checkpoint(store):
    position = recording(store)
    saved = position.drafts.load()
    with pytest.raises(ValueError, match="changed elsewhere"):
        position.drafts.save(saved, saved["revision"] - 1)
    assert position.drafts.load() == saved
    position.close()
