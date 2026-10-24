from pathlib import Path

import cv2
import numpy as np
import pytest

from maplebot.config import PerceptionConfig
from maplebot.geometry import Rect
from maplebot.perception import CameraTracker, TemplateDetector


def sprite(seed: int, height: int = 28, width: int = 24) -> np.ndarray:
    # Deliberately synthetic, textured sprites; not evidence about MapleUnity artwork.
    image = np.random.default_rng(seed).integers(20, 230, (height, width, 3), dtype=np.uint8)
    cv2.rectangle(image, (2, 2), (width - 3, height - 3), (50, 240, 90), 1)
    return image


def templates(directory: Path) -> tuple[np.ndarray, np.ndarray]:
    player, monster = sprite(1), sprite(2)
    for kind, image in (("player", player), ("monster", monster)):
        path = directory / kind
        path.mkdir(parents=True)
        cv2.imwrite(str(path / "pose.png"), image)
    return player, monster


def test_detects_sprites_and_mirrored_pose_with_confidence(tmp_path):
    player, monster = templates(tmp_path)
    image = np.full((160, 260, 3), 30, dtype=np.uint8)
    image[90:118, 20:44] = player
    image[90:118, 180:204] = cv2.flip(monster, 1)
    result = TemplateDetector(tmp_path, PerceptionConfig()).detect(image)
    assert result.player is not None
    assert result.player.box == Rect(20, 90, 24, 28)
    assert result.player.confidence > 0.99
    strong = [item for item in result.monsters if item.confidence >= 0.9]
    assert len(strong) == 1
    assert strong[0].box == Rect(180, 90, 24, 28)


def test_ambiguous_players_and_blank_frames_are_not_trusted(tmp_path):
    player, _ = templates(tmp_path)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    blank = np.full((160, 260, 3), 30, dtype=np.uint8)
    assert detector.detect(blank).player is None
    blank[90:118, 20:44] = player
    blank[90:118, 180:204] = player
    result = detector.detect(blank)
    assert result.player is None
    assert any("Ambiguous" in failure for failure in result.failures)


def test_camera_tracks_global_translation_and_rejects_flat_frames():
    tracker = CameraTracker()
    frame = np.random.default_rng(9).integers(0, 255, (200, 320, 3), dtype=np.uint8)
    tracker.update(frame)
    shifted = cv2.warpAffine(frame, np.float32([[1, 0, -20], [0, 1, 6]]), (320, 200))
    (dx, dy), confidence = tracker.update(shifted)
    assert dx == pytest.approx(-20, abs=1)
    assert dy == pytest.approx(6, abs=1)
    assert confidence > 0.35
    assert tracker.update(np.zeros_like(frame)) == ((0, 0), 0)


def test_flat_templates_rejected():
    with pytest.raises(ValueError, match="textured sprite"):
        TemplateDetector.validate(np.full((24, 24, 3), 90, dtype=np.uint8))


def player_example(background, *, walking=False, mirrored=False):
    image = np.full((96, 76, 3), background, dtype=np.uint8)
    layer = np.zeros_like(image)
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    for output, color in ((layer, (190, 190, 190)), (mask, 255)):
        cv2.ellipse(output, (38, 25), (18, 13), 0, 0, 360, color, -1)
    cv2.ellipse(layer, (38, 25), (18, 13), 0, 0, 360, (25, 25, 25), 2)
    cv2.line(layer, (25, 21), (49, 21), (225, 225, 225), 1)
    cv2.line(layer, (24, 26), (50, 26), (120, 120, 120), 1)
    for output, color in ((layer, (185, 220, 245)), (mask, 255)):
        cv2.ellipse(output, (38, 40), (12, 9), 0, 0, 360, color, -1)
    cv2.circle(layer, (33, 39), 3, (30, 50, 140), -1)
    cv2.circle(layer, (43, 39), 3, (20, 20, 20), -1)
    for output, color in ((layer, (240, 240, 240)), (mask, 255)):
        cv2.rectangle(output, (31, 50), (44, 65), color, -1)
        cv2.rectangle(output, (17, 27), (22, 36), color, -1)
        cv2.line(output, (34, 65), (25 if walking else 34, 75), color, 4)
        cv2.line(output, (42, 65), (51 if walking else 42, 75), color, 4)
    if mirrored:
        layer, mask = cv2.flip(layer, 1), cv2.flip(mask, 1)
    image[mask != 0] = layer[mask != 0]
    cv2.putText(image, "PLAYER", (5, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (240, 240, 240), 1)
    return image


@pytest.mark.parametrize("mirrored", [False, True])
def test_player_survives_changed_background_walking_pose_and_direction(tmp_path, mirrored):
    directory = tmp_path / "player"
    directory.mkdir()
    cv2.imwrite(str(directory / "standing.png"), player_example((50, 100, 150)))
    frame = np.full((210, 300, 3), (150, 70, 35), dtype=np.uint8)
    frame[42:138, 120:196] = player_example((150, 70, 35), walking=True, mirrored=mirrored)
    result = TemplateDetector(tmp_path, PerceptionConfig()).detect(frame)
    assert result.player is not None
    assert result.player.box == Rect(120, 42, 76, 96)
    assert result.player.confidence >= 0.9


def test_player_is_not_inferred_from_the_old_background_or_nameplate(tmp_path):
    directory = tmp_path / "player"
    directory.mkdir()
    reference = player_example((50, 100, 150))
    cv2.imwrite(str(directory / "standing.png"), reference)
    frame = np.full((210, 300, 3), (50, 100, 150), dtype=np.uint8)
    frame[40:136, 30:106] = reference
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    assert detector.detect(frame).player is not None
    # The scenery and label remain, but the player has left this location.
    frame[40:120, 30:106] = (50, 100, 150)
    result = detector.detect(frame)
    assert result.player is None


def test_foreground_player_matches_still_reject_ambiguous_characters(tmp_path):
    directory = tmp_path / "player"
    directory.mkdir()
    cv2.imwrite(str(directory / "standing.png"), player_example((50, 100, 150)))
    frame = np.full((210, 300, 3), (150, 70, 35), dtype=np.uint8)
    for x in (20, 170):
        frame[42:138, x : x + 76] = player_example((150, 70, 35), walking=True)
    result = TemplateDetector(tmp_path, PerceptionConfig()).detect(frame)
    assert result.player is None
    assert any("Ambiguous" in failure for failure in result.failures)


@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("color_delta", [0, 2])
def test_transparent_enemy_references_match_multiple_enemies_on_new_background(
    tmp_path, mirrored, color_delta
):
    directory = tmp_path / "monster"
    directory.mkdir()
    example = np.zeros((30, 40, 4), dtype=np.uint8)
    cv2.ellipse(example, (20, 15), (14, 10), 0, 0, 360, (30, 120, 220, 255), -1)
    cv2.circle(example, (12, 12), 3, (245, 245, 245, 255), -1)
    cv2.circle(example, (13, 12), 1, (10, 10, 10, 255), -1)
    cv2.rectangle(example, (22, 16), (27, 18), (10, 10, 10, 255), -1)
    cv2.imwrite(str(directory / "reference.png"), example)
    frame = np.full((160, 300, 3), (170, 65, 30), dtype=np.uint8)
    sprite = cv2.flip(example, 1) if mirrored else example
    sprite[:, :, :3] = np.clip(sprite[:, :, :3].astype(np.int16) + color_delta, 0, 255)
    for x in (40, 200):
        patch = frame[70:100, x : x + 40]
        patch[sprite[:, :, 3] != 0] = sprite[:, :, :3][sprite[:, :, 3] != 0]
    result = TemplateDetector(tmp_path, PerceptionConfig()).detect(frame)
    strong = [item for item in result.monsters if item.confidence >= 0.9]
    assert len(strong) == 2
    assert {item.box for item in strong} == {Rect(40, 70, 40, 30), Rect(200, 70, 40, 30)}
