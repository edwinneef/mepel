import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from maplebot.config import PerceptionConfig
from maplebot.geometry import Rect
from maplebot.perception import CameraTracker, TemplateDetector


def test_annotation_does_not_cover_game_pixels_with_a_status_strip(tmp_path):
    from maplebot.perception import annotate

    image = np.random.default_rng(45).integers(0, 255, (120, 160, 3), dtype=np.uint8)
    observation = TemplateDetector(tmp_path, PerceptionConfig()).detect(image)

    output = annotate(image, observation, None, "IDLE", "Emergency stop hotkey")

    assert output.shape == image.shape
    np.testing.assert_array_equal(output, image)


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



def test_added_player_template_matches_like_a_full_reload_without_rereading(tmp_path, monkeypatch):
    templates(tmp_path)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    geared = sprite(7)
    path = tmp_path / "player" / "geared.png"
    cv2.imwrite(str(path), geared)
    monkeypatch.setattr(detector, "reload", lambda: pytest.fail("add must not reload"))
    detector.add(path, "player")
    reloaded = TemplateDetector(tmp_path, PerceptionConfig())
    names = sorted((item.kind, item.name) for item in detector.templates)
    assert names == sorted((item.kind, item.name) for item in reloaded.templates)
    image = np.full((160, 260, 3), 30, dtype=np.uint8)
    image[90:118, 20:44] = cv2.flip(geared, 1)
    result = detector.detect(image)
    assert result.player is not None and result.player.template == "geared"

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


@pytest.mark.parametrize("obscured_samples", [(0,), (12,), (0, 1, 2), tuple(range(5))])
def test_obscured_signature_pixels_do_not_hide_a_confident_monster(tmp_path, obscured_samples):
    directory = tmp_path / "monster"
    directory.mkdir()
    rng = np.random.default_rng(71)
    example = np.zeros((36, 36, 4), dtype=np.uint8)
    example[2:34, 2:34, :3] = rng.integers(20, 240, (32, 32, 3), dtype=np.uint8)
    example[2:34, 2:34, 3] = 255
    cv2.imwrite(str(directory / "reference.png"), example)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    frame = np.full((120, 160, 3), 80, dtype=np.uint8)
    patch = frame[40:76, 60:96]
    patch[example[:, :, 3] != 0] = example[:, :, :3][example[:, :, 3] != 0]
    # Exercise both an indexed proposal pixel and a later verification sample.
    for sample in obscured_samples:
        y, x = detector.templates[0].signature.offsets[sample]
        patch[y, x] = 255 - patch[y, x]
    result = detector.detect(frame)
    assert any(
        item.box == Rect(60, 40, 36, 36) and item.confidence >= 0.9 for item in result.monsters
    )
    # Matching the sampled colors alone must still fail full-sprite verification.
    patch[:] = 80
    signature = detector.templates[0].signature
    patch[signature.offsets[:, 0], signature.offsets[:, 1]] = signature.colors
    assert not any(item.confidence >= 0.9 for item in detector.detect(frame).monsters)


def name_tag(seed: int = 3) -> np.ndarray:
    # Synthetic stand-in for a name label: white glyph strokes on a dark box.
    tag = np.full((13, 60, 3), 40, dtype=np.uint8)
    rng = np.random.default_rng(seed)
    for x in range(3, 56, 4):
        top = int(rng.integers(2, 5))
        tag[top : top + int(rng.integers(4, 8)), x : x + 2] = 255
        tag[int(rng.integers(3, 9)), x : x + 3] = 255
    return tag


def teach_tag(directory: Path, tag: np.ndarray, **meta) -> None:
    folder = directory / "nametag"
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / "name.png"), tag)
    if meta:
        (folder / "name.json").write_text(json.dumps(meta), encoding="utf-8")


def scenery(seed: int = 5) -> np.ndarray:
    frame = np.random.default_rng(seed).integers(60, 200, (240, 320, 3), dtype=np.uint8)
    return cv2.GaussianBlur(frame, (9, 9), 0)


def test_name_tag_locates_player_after_gear_change_and_derives_feet(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag, player_size=[30, 50])
    frame = scenery()
    frame[150:163, 100:160] = tag
    result = TemplateDetector(tmp_path, PerceptionConfig()).detect(frame)
    assert result.player is not None
    text_top = int(np.nonzero(tag[:, :, 0] >= 200)[0].min())
    # Centred on the glyphs, which span x 102..158 in this synthetic tag.
    assert result.player.box == Rect(116, 150 + text_top - 2 - 50, 30, 50)
    assert result.player.template == "nametag:name:tag-only"
    assert any("located by name tag" in failure for failure in result.failures)


def test_name_tag_ignores_static_decoys_and_light_backgrounds(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag, decoys=[[20, 220]], frame=[320, 240])
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    frame = scenery()
    frame[220:233, 20:80] = tag  # HUD copy recorded when the tag was taught
    chat = tag.copy()
    chat[chat < 250] = 250  # Same glyphs on a near-white background
    frame[40:53, 200:260] = chat
    assert detector.detect(frame).player is None
    frame[150:163, 100:160] = tag
    result = detector.detect(frame)
    assert result.player is not None and result.player.box.x == 108


def test_name_tag_and_distant_sprite_disagreement_is_not_trusted(tmp_path):
    player, _ = templates(tmp_path)
    tag = name_tag()
    teach_tag(tmp_path, tag)
    frame = scenery()
    frame[150:163, 30:90] = tag
    frame[60:88, 250:274] = player
    result = TemplateDetector(tmp_path, PerceptionConfig()).detect(frame)
    assert result.player is None
    assert any("disagree" in failure for failure in result.failures)


def test_two_identical_name_tags_fall_back_to_the_sprite(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag)
    frame = scenery()
    frame[150:163, 30:90] = tag
    frame[150:163, 200:260] = tag
    result = TemplateDetector(tmp_path, PerceptionConfig()).detect(frame)
    assert result.player is None
    assert any("Ambiguous name tag" in failure for failure in result.failures)


def tag_scene(tag: np.ndarray, x: int = 110, y: int = 150, sprite: bool = False) -> np.ndarray:
    frame = np.full((240, 320, 3), (150, 70, 35), dtype=np.uint8)
    frame[y : y + 13, x : x + 60] = tag
    if sprite:
        feet = y + int(np.nonzero(tag[:, :, 0] >= 200)[0].min()) - 2
        frame[feet - 75 : feet + 1, x - 8 : x + 68] = player_example((150, 70, 35))[:76]
    return frame


def test_clean_tag_refreshes_sprite_so_new_outfit_is_found_with_tag_covered(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    frame = tag_scene(tag, sprite=True)
    assert detector.detect(frame, now=0).player.template == "nametag:name:tag-only"
    assert detector.fresh
    frame[150:163, 110:170] = (90, 140, 60)  # Grass covers the whole tag.
    result = detector.detect(frame, now=10)
    assert result.player is not None
    assert result.player.template.startswith("fresh:")
    assert not result.player.tracked


def test_partly_covered_tag_is_tracked_only_near_last_position_and_briefly(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    confirmed = detector.detect(tag_scene(tag), now=0).player
    covered = tag.copy()
    covered[:, 30:] = (90, 140, 60)
    result = detector.detect(tag_scene(covered), now=0.3)
    assert result.player is not None and result.player.tracked
    assert result.player.box == confirmed.box
    assert result.player.confidence < 0.9
    assert detector.detect(tag_scene(covered), now=1.5).player is None


def test_partly_covered_tag_far_from_last_position_is_not_tracked(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    detector.detect(tag_scene(tag), now=0)
    covered = tag.copy()
    covered[:, 30:] = (90, 140, 60)
    assert detector.detect(tag_scene(covered, x=250), now=0.3).player is None


def test_conflicting_tag_and_sprite_drops_fresh_sprites_and_track(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag)
    (tmp_path / "player").mkdir()
    cv2.imwrite(str(tmp_path / "player" / "pose.png"), player_example((150, 70, 35))[:76])
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    detector.detect(tag_scene(tag, sprite=True), now=0)
    assert detector.fresh and detector.track
    frame = tag_scene(tag, x=230)
    frame[60:136, 20:96] = player_example((150, 70, 35))[:76]
    result = detector.detect(frame, now=0.2)
    assert result.player is None
    assert not detector.fresh and detector.track is None


def test_name_tag_over_bright_clouds_is_still_found(tmp_path):
    # Over white clouds the translucent box turns light grey (up to ~240 in recordings).
    tag = name_tag()
    teach_tag(tmp_path, tag)
    cloudy = tag.copy()
    cloudy[cloudy < 200] = 235
    frame = tag_scene(cloudy)
    frame[:, :] = np.where(frame == (150, 70, 35), 250, frame)
    result = TemplateDetector(tmp_path, PerceptionConfig()).detect(frame)
    assert result.player is not None
    assert result.player.confidence >= 0.9


def test_name_tag_running_off_the_frame_edge_is_still_found(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag)
    wide = np.full((240, 400, 3), (150, 70, 35), dtype=np.uint8)
    wide[150:163, 266:326] = tag
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    reference = detector.detect(wide, now=0).player
    # Crop so the last columns of the tag fall outside the frame.
    clipped = TemplateDetector(tmp_path, PerceptionConfig()).detect(
        np.ascontiguousarray(wide[:, :320]), now=0
    )
    assert clipped.player is not None
    assert clipped.player.box == reference.box


def test_partial_evidence_chains_tracking_up_to_the_cap(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    detector.detect(tag_scene(tag), now=0)
    covered = tag.copy()
    covered[:, 30:] = (90, 140, 60)
    for now in (0.4, 1.2, 2.0, 2.8, 3.6, 4.4):
        player = detector.detect(tag_scene(covered), now=now).player
        assert player is not None and player.tracked
    assert detector.detect(tag_scene(covered), now=5.2).player is None


def test_tracking_chain_ends_after_a_gap_without_evidence(tmp_path):
    tag = name_tag()
    teach_tag(tmp_path, tag)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    detector.detect(tag_scene(tag), now=0)
    covered = tag.copy()
    covered[:, 30:] = (90, 140, 60)
    hidden = tag.copy()
    hidden[:] = (90, 140, 60)
    assert detector.detect(tag_scene(covered), now=0.5).player.tracked
    assert detector.detect(tag_scene(hidden), now=1.0).player is None
    assert detector.detect(tag_scene(covered), now=1.6).player is None


def test_search_window_follows_the_player_and_reports_full_frame_coordinates(tmp_path):
    player, monster = templates(tmp_path)
    config = PerceptionConfig(roi_width=200, roi_height=200)
    detector = TemplateDetector(tmp_path, config)
    frame = np.full((400, 600, 3), 30, dtype=np.uint8)
    frame[300:328, 400:424] = player
    frame[300:328, 470:494] = monster
    seen = []
    original = detector._observe

    def spy(image, *args):
        seen.append(image.shape[:2])
        return original(image, *args)

    detector._observe = spy
    first = detector.detect(frame, 0.0)
    assert seen == [(400, 600)] and first.player.box == Rect(400, 300, 24, 28)
    frame[300:328, 400:424] = 30
    frame[300:328, 410:434] = player
    second = detector.detect(frame, 0.3)
    assert seen[1] == (200, 200)
    assert second.player.box == Rect(410, 300, 24, 28)
    assert [m.box for m in second.monsters if m.confidence >= 0.9] == [Rect(470, 300, 24, 28)]


def test_search_window_falls_back_to_the_whole_frame_when_the_player_jumps_away(tmp_path):
    player, _ = templates(tmp_path)
    detector = TemplateDetector(tmp_path, PerceptionConfig(roi_width=200, roi_height=200))
    frame = np.full((400, 600, 3), 30, dtype=np.uint8)
    frame[300:328, 100:124] = player
    assert detector.detect(frame, 0.0).player.box == Rect(100, 300, 24, 28)
    frame[300:328, 100:124] = 30
    frame[40:68, 500:524] = player
    moved = detector.detect(frame, 0.3)
    assert moved.player is not None and moved.player.box == Rect(500, 40, 24, 28)


def test_search_window_size_is_validated_and_zero_disables_it(tmp_path):
    from maplebot.config import Config

    for value, valid in ((0, True), (100, False), (200, True)):
        path = tmp_path / f"{value}.toml"
        path.write_text(f"[perception]\nroi_width = {value}\n", encoding="utf-8")
        if valid:
            assert Config.load(path).perception.roi_width == value
        else:
            with pytest.raises(ValueError, match="roi_width"):
                Config.load(path)
