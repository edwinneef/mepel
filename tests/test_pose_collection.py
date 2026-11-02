import json
import time
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest

from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation
from maplebot.pose_collection import PoseCollection


@pytest.fixture
def store(tmp_path):
    value = PoseCollection(tmp_path, limit=3, interval=3)
    yield value
    value.close()


def sample(store, value=80):
    store.submit(np.full((32, 44, 3), value, np.uint8),
                 np.full((32, 44), 255, np.uint8),
                 asdict(Rect(0, 0, 44, 32)), {"source_sha256": "fixture"})


def settle(store):
    deadline = time.monotonic() + 2
    while store.jobs.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(.005)
    assert store.jobs.unfinished_tasks == 0


def test_off_dedup_persistence_and_identity_isolation(store):
    sample(store)
    assert not list(store.root.rglob("*.json"))
    store.configure("alice", "first")
    sample(store)
    sample(store, 81)
    settle(store)
    assert store.saved == 1 and store.duplicates == 1
    store.configure()
    store.configure("alice", "first")
    sample(store)
    assert store.saved == 1 and store.duplicates == 1
    store.configure("bob", "first")
    sample(store)
    settle(store)
    assert len(list(store.root.rglob("*.json"))) == 2
    data = json.loads(next((store.root / "alice").rglob("*.json")).read_text())
    assert data["candidate_only"] and data["source_sha256"] == "fixture"


def test_distinct_outfits_and_full_never_delete(store):
    store.configure("alice", "first")
    for color in (40, 90, 150):
        sample(store, color)
        settle(store)
    assert not store.enabled and store.reason == "Full"
    assert store.saved == 3
    store.configure("alice", "second")
    sample(store)
    settle(store)
    assert len(list(store.root.rglob("*.json"))) == 4


def test_write_failure_stops_collection(store, monkeypatch):
    store.configure("alice", "first")
    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(type(store.root), "mkdir", fail)
    sample(store)
    settle(store)
    assert not store.enabled and "disk full" in store.reason
    assert store.saved == 0


def test_bad_identity_and_corrupt_storage_preserved(store):
    with pytest.raises(ValueError):
        store.configure("../alice", "first")
    directory = store.root / "alice" / "first"
    directory.mkdir(parents=True)
    bad = directory / "bad.json"
    bad.write_text("broken")
    with pytest.raises(ValueError):
        store.configure("alice", "first")
    assert bad.read_text() == "broken" and not store.enabled


def fixture_observation():
    body = Rect(20, 20, 44, 64)
    tag = SimpleNamespace(name="alice")
    match = Detection("nametag", Rect(10, 90, 70, 10), 1, "alice")
    detector = SimpleNamespace(
        nametags=[tag], nametag_matches=lambda *args: [match],
        body_from_nametag=lambda *args: body,
        _player_anchor=lambda crop: (Rect(0, 0, 44, 64), np.full((64, 44), 255, np.uint8)),
    )
    observation = Observation(Detection("player", body, 1, "nametag:alice:tag-only"), [])
    return detector, observation


@pytest.mark.parametrize("invalid", [
    "stale", "tracked", "ambiguous", "overlap", "generation", "disabled",
])
def test_rejects_invalid_second_observation(store, invalid):
    store.configure("alice", "first")
    detector, observation = fixture_observation()
    image = np.full((160, 200, 3), 100, np.uint8)
    store.observe(image, detector, observation, 1, time.time(), 1, eligible=True)
    if invalid == "tracked":
        observation = Observation(Detection("player", observation.player.box, 1, tracked=True), [])
    if invalid == "ambiguous":
        observation.failures.append("Ambiguous player")
    if invalid == "overlap":
        observation.monsters.append(Detection("monster", observation.player.box, 1))
    store.observe(image, detector, observation, 1.1,
                  time.time() - (1 if invalid == "stale" else 0),
                  2 if invalid == "generation" else 1, eligible=invalid != "disabled")
    assert not store.examples


def test_two_frames_and_throttle(store):
    store.configure("alice", "first")
    detector, observation = fixture_observation()
    image = np.full((160, 200, 3), 100, np.uint8)
    for now in (1, 1.1, 1.2):
        store.observe(image, detector, observation, now, time.time(), 1, eligible=True)
    settle(store)
    assert store.saved == 1 and store.duplicates == 0


def test_queue_saturation_skips_without_blocking(store, monkeypatch):
    import queue

    store.configure("alice", "first")
    monkeypatch.setattr(store.jobs, "put_nowait", lambda job: (_ for _ in ()).throw(queue.Full()))
    sample(store)
    assert not store.examples and store.reason == "Writer busy; sample skipped"


def test_close_drains_and_disables_new_samples(store):
    store.configure('alice', 'one')
    sample(store)
    store.close()
    assert not store.enabled and store.saved == 1
    assert not store.writer.is_alive()
    sample(store, 180)
    assert store.saved == 1


def test_capture_timeout_and_preview(store):
    store.configure("name", "new")
    sample(store)
    settle(store)
    assert len(store.snapshot()["candidates"]) == 1
    store.deadline = time.monotonic() - 1
    assert not store.snapshot()["enabled"]
    assert store.snapshot()["reason"] == "Capture complete"
    assert store.snapshot()["candidates"][0]["crop"]


@pytest.mark.parametrize("duplicate", [True, False])
def test_duplicate_name_templates_do_not_count_as_another_player(store, duplicate):
    store.configure("alice", "first")
    detector, observation = fixture_observation()
    tag = detector.nametags[0]
    tag.text = np.ones((10, 70), np.uint8)
    other = SimpleNamespace(name="alias", text=tag.text.copy())
    detector.nametags.append(other)
    original = detector.nametag_matches
    other_box = Rect(10 if duplicate else 80, 90, 70, 10)
    detector.nametag_matches = lambda gray, taught, score: (
        original(gray, taught, score) if taught is tag else
        [Detection("nametag", other_box, 1, "alias")])
    image = np.full((160, 200, 3), 100, np.uint8)
    for now in (1, 1.1):
        store.observe(image, detector, observation, now, time.time(), 1, eligible=True)
    settle(store)
    assert store.saved == int(duplicate)
    if not duplicate:
        store.deadline = time.monotonic() - 1
        status = store.snapshot()
        assert not status["enabled"]
        assert status["last_rejection"] == "Nearby appearance overlaps collection"
        assert status["rejection_reasons"][status["last_rejection"]] == 2
