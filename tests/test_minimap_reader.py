import numpy as np
import pytest

from maplebot.minimap_reader import DOT_SHAPE, AreaMinimap, describe

SKY = (235, 180, 90)


def view(dots=((60, 20),), *, at=(13, 72), seed=1, size=(768, 1366)):
    """A game view with a navy minimap, opaque terrain under it and a white rim."""
    image = np.full((*size, 3), SKY, np.uint8)
    x, y = at
    image[y:y + 40, x:x + 183] = (100, 60, 30)
    terrain = np.random.default_rng(seed).integers(40, 141, (24, 183, 3), dtype=np.uint8)
    terrain[..., 2] = np.maximum(terrain[..., 2], 60)
    image[y + 40:y + 64, x:x + 183] = terrain
    image[y + 64, x:x + 183] = 255
    for dx, dy in dots:
        patch = image[y + dy:y + dy + 6, x + dx:x + dx + 6]
        patch[DOT_SHAPE] = (0, 220, 255)
    return image


@pytest.fixture
def reader():
    return AreaMinimap(view())


def test_reference_view_reads_one_player_marker(reader):
    fix = reader.read(view(((90, 10),)))
    assert fix.dot == (92.5, 12.5) and fix.candidates == 1
    assert (fix.canvas.x, fix.canvas.y, fix.canvas.width, fix.canvas.height) == (13, 72, 183, 64)


def test_moved_minimap_keeps_marker_in_canvas_coordinates(reader):
    fix = reader.read(view(((90, 10),), at=(6, 29)))
    assert fix.dot == (92.5, 12.5) and (fix.canvas.x, fix.canvas.y) == (6, 29)


@pytest.mark.parametrize(("image", "reason"), [
    (np.full((768, 1366, 3), SKY, np.uint8), "Minimap missing"),
    (view(seed=2), "Minimap missing"),
    (view(()), "No player marker"),
    (view(((30, 10), (120, 20))), "Several player markers"),
    (view(size=(766, 1023)), "Capture size differs"),
])
def test_covered_other_map_or_ambiguous_markers_are_unknown(reader, image, reason):
    fix = reader.read(image)
    assert fix.dot is None and fix.reason.startswith(reason)


def test_reference_without_minimap_is_rejected():
    with pytest.raises(ValueError, match="No minimap"):
        AreaMinimap(np.full((768, 1366, 3), SKY, np.uint8))
    assert describe(np.full((768, 1366, 3), SKY, np.uint8)) is None


def test_describe_stores_canvas_and_marker():
    assert describe(view()) == {
        "canvas": {"x": 13, "y": 72, "width": 183, "height": 64}, "dot": {"x": 62.5, "y": 22.5},
    }


def test_minimap_without_navy_is_found_by_its_white_frame():
    image = np.full((768, 1366, 3), SKY, np.uint8)
    image[71:143, 3:140] = 255
    art = np.random.default_rng(5).integers(40, 141, (70, 135, 3), dtype=np.uint8)
    image[72:142, 4:139] = art
    image[72 + 40:72 + 46, 4 + 100:4 + 106][DOT_SHAPE] = (0, 220, 255)
    assert describe(image) == {"canvas": {"x": 4, "y": 72, "width": 135, "height": 70},
                               "dot": {"x": 102.5, "y": 42.5}}
    assert AreaMinimap(image).read(image).dot == (102.5, 42.5)


@pytest.mark.parametrize("background", [(82, 82, 82), (210, 200, 190)])
@pytest.mark.parametrize("at", [(4, 72), (42, 92)])
def test_translucent_grey_sky_is_ignored_when_matching_the_map(background, at):
    image = np.full((768, 1366, 3), SKY, np.uint8)
    image[71:143, 3:140] = 255
    image[72:142, 4:139] = background  # translucent grey sky, including bright scenery
    terrain = np.random.default_rng(6).integers(40, 141, (30, 135, 3), dtype=np.uint8)
    terrain[..., 2] = np.maximum(terrain[..., 2], 120)  # saturated, opaque rock
    image[112:142, 4:139] = terrain
    image[115:121, 64:70][DOT_SHAPE] = (0, 220, 255)
    reader = AreaMinimap(image)
    scrolled = image.copy()
    scrolled[72:112, 4:139] = (120, 110, 95)  # scenery behind the sky changed
    moved = np.full_like(scrolled, SKY)
    x, y = at
    moved[y - 1:y + 71, x - 1:x + 136] = 255
    moved[y:y + 70, x:x + 135] = scrolled[72:142, 4:139]
    fix = reader.read(moved)
    assert fix.reason == "Player marker on the taught map"
    assert fix.dot == (62.5, 45.5)
    assert (fix.canvas.x, fix.canvas.y) == at


def test_blue_sky_through_the_minimap_is_not_static_terrain():
    image = view(((60, 50),))
    image[76:102, 17:192] = (200, 150, 90)  # blue sky behind the translucent background
    reader = AreaMinimap(image)
    scrolled = image.copy()
    scrolled[76:102, 17:192] = (40, 70, 60)  # the camera moved; dark trees show through
    assert reader.read(scrolled).dot == (62.5, 52.5)


def test_dark_saturated_background_is_not_static_terrain():
    image = view(((60, 50),))
    # Dark brown scenery through a translucent background was retained by the grey mask.
    image[76:102, 17:192] = (25, 45, 70)
    reader = AreaMinimap(image)
    scrolled = image.copy()
    scrolled[76:102, 17:192] = (15, 20, 30)
    assert reader.read(scrolled).dot == (62.5, 52.5)


def test_dark_only_reference_cannot_supply_identity_evidence():
    image = view()
    image[71:137, 12:197] = 255
    image[72:136, 13:196] = (25, 45, 70)
    with pytest.raises(ValueError, match="too little terrain"):
        AreaMinimap(image)
