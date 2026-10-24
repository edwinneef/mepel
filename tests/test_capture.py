from dataclasses import replace

import pytest

from maplebot.capture import Calibration
from maplebot.geometry import Rect
from maplebot.windows import Window


def test_crop_tracks_window_movement_in_physical_pixels():
    window = Window(1, "MapleUnity", Rect(-1500, 100, 1200, 900), True, 144)
    calibration = Calibration(window.title, 1200, 900, 144, Rect(100, 80, 1024, 768))
    assert calibration.valid_for(window)
    assert calibration.crop.translated(window.client.x, window.client.y) == Rect(
        -1400, 180, 1024, 768
    )
    moved = replace(window, client=Rect(150, 200, 1200, 900))
    assert calibration.valid_for(moved)
    assert calibration.crop.translated(moved.client.x, moved.client.y) == Rect(250, 280, 1024, 768)


@pytest.mark.parametrize(
    "changed",
    [
        {"client": Rect(0, 0, 1201, 900)},
        {"dpi": 96},
        {"title": "Different Editor"},
    ],
)
def test_resize_dpi_and_title_invalidate_calibration(changed):
    window = Window(1, "MapleUnity", Rect(0, 0, 1200, 900), True, 144)
    calibration = Calibration(window.title, 1200, 900, 144, Rect(100, 80, 1024, 768), True, True)
    assert not calibration.valid_for(replace(window, **changed))


def test_calibration_persists_crop_but_does_not_restore_live_permissions(tmp_path):
    path = tmp_path / "calibration.json"
    calibration = Calibration("MapleUnity", 1200, 900, 144, Rect(100, 80, 1024, 768), True, True)
    calibration.save(path)
    calibration.save(path)
    loaded = Calibration.load(path)
    assert loaded.crop == calibration.crop
    assert not loaded.capture_verified
    assert not loaded.controls_verified
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_invalid_rectangle_is_rejected():
    with pytest.raises(ValueError):
        Rect(0, 0, 0, 10)
