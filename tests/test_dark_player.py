from pathlib import Path

import cv2
import numpy as np
import pytest

from maplebot.config import PerceptionConfig
from maplebot.perception import TemplateDetector
from maplebot.reacquisition import Reacquisition

FIXTURE = Path(__file__).parent / "fixtures/fh374-dark-player"
IDENTITY = "nametag:22a29d3dba27468f9909f9f685bd85a1"
POSE = "d168a73ddb5b42c6a86b1aa27da2bf6d"


def frame(number):
    return cv2.imread(str(FIXTURE / f"{number:08}.png"))


def observe(detector, number, now):
    return detector._observe(frame(number), now, detector.templates, .7)[0]


@pytest.fixture
def detector():
    detector = TemplateDetector(FIXTURE, PerceptionConfig(confidence=.85,
                                                        nametag_confidence=.85))
    player = observe(detector, 1321, 1)
    assert player.template == IDENTITY and not player.tracked
    assert detector.confirmed_sprites.names[POSE] == IDENTITY
    yield detector
    detector.pool.shutdown(wait=True)
    detector.map_filter.close()


@pytest.mark.parametrize("number", [1320, 1339, 1340, 1342, 1344, 1406, 1425])
def test_recorded_dark_pose_keeps_fresh_named_identity(detector, number):
    player = observe(detector, number, 1.2)
    assert player is not None and not player.tracked
    assert player.confidence >= .9
    assert player.identity == IDENTITY or player.template == IDENTITY


def test_bright_dark_sequence_no_longer_resets_recovery(detector):
    recovery = Reacquisition()
    recovery.step(IDENTITY, 1)
    for index, number in enumerate([1339, 1340, 1341, 1342, 1343, 1344, 1345], 1):
        now = 1 + index * .2
        player = observe(detector, number, now)
        identity = player.identity or player.template.removesuffix(":tag-only")
        assert not player.tracked and recovery.step(identity, now).state == "ok"


@pytest.mark.parametrize("gate", ["cold", "expired", "backward", "lookalike", "collision",
                                  "wrong-name", "unlearned", "distant"])
def test_dark_pose_cannot_bypass_identity_gates(detector, gate):
    now = 1.2
    if gate == "cold":
        detector.confirmed_sprites.last = None
    elif gate == "expired":
        now = 5
    elif gate == "backward":
        now = .9
    elif gate == "lookalike":
        detector.lookalike_at = 1.1
    elif gate == "collision":
        detector.confirmed_sprites.names[POSE] = None
    elif gate == "wrong-name":
        detector.confirmed_sprites.names[POSE] = "nametag:another-player"
    elif gate == "unlearned":
        detector.confirmed_sprites.names.clear()
    elif gate == "distant":
        identity, box, at = detector.confirmed_sprites.last
        detector.confirmed_sprites.last = (identity, box.translated(200, 0), at)
    image = frame(1339)
    assert not detector._dark_player_candidates(image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), now)


def test_nonzero_search_origin_preserves_named_identity(detector):
    image = frame(1339)
    origin = (100, 200)
    identity, box, at = detector.confirmed_sprites.last
    detector.confirmed_sprites.last = (identity, box.translated(*origin), at)
    detector.origin = origin
    candidates = detector._dark_player_candidates(
        image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1.2)
    assert candidates and max(p.confidence for p in candidates) >= .9


def test_dark_matching_rejects_missing_player_and_pet_terrain_pixels(detector):
    image = frame(1339)
    # Replace the entire character with a nearby patch of platform/pet/background.
    image[30:120, 65:140] = image[30:120, 145:220]
    assert not detector._dark_player_candidates(image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1.2)
    blank = np.zeros_like(image)
    assert not detector._dark_player_candidates(blank, cv2.cvtColor(blank, cv2.COLOR_BGR2GRAY), 1.3)


def test_two_dark_lookalikes_cannot_supply_fresh_identity(detector):
    original = frame(1339)
    image = np.zeros((210, 320, 3), dtype=np.uint8)
    image[:, :220] = original
    image[20:130, 135:215] = original[20:130, 65:145]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    candidates = detector._suppress(detector._dark_player_candidates(image, gray, 1.5))
    assert len(candidates) >= 2
    player, _, _ = detector._resolve(candidates, [], [], gray, 1.5)
    assert player is None or player.identity is None
    assert detector.confirmed_sprites.last is None
