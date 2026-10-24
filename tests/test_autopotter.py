import cv2
import numpy as np
import pytest

from maplebot.autopotter import PotionMonitor
from maplebot.geometry import Rect


def hud(hp=100, mp=100):
    image = np.full((100, 300, 3), 85, dtype=np.uint8)
    for x, percent, color in [(10, hp, (0, 0, 210)), (150, mp, (210, 110, 0))]:
        cv2.rectangle(image, (x, 30), (x + 103, 45), (235, 235, 235), 1)
        image[31:45, x + 1 : x + 103] = 20
        image[31:45, x + 1 : x + 1 + round(102 * percent / 100)] = color
    return image


def monitor(tmp_path):
    result = PotionMonitor(tmp_path / "autopotter.json")
    for resource, x in [("hp", 10), ("mp", 150)]:
        result.calibrate(resource, hud(), Rect(x, 30, 104, 16))
    result.start()
    return result


@pytest.mark.parametrize("percent", [0, 25, 50, 75, 100])
def test_bar_reading_is_from_pixels_with_a_stable_hud_anchor(tmp_path, percent):
    potter = monitor(tmp_path)
    status = potter.observe(hud(percent, percent), 0)
    for resource in ["hp", "mp"]:
        reading = status["readings"][resource]
        assert reading["percent"] == pytest.approx(percent, abs=2)
        assert reading["confidence"] >= 0.9


def test_low_hp_takes_priority_and_cooldown_prevents_repeated_suggestions(tmp_path):
    potter = monitor(tmp_path)
    assert potter.observe(hud(20, 10), 0)["suggestion"] is None
    first = potter.observe(hud(20, 10), 0.1)
    assert first["suggestion"] == "hp"
    assert first["input_sent"] is False
    assert potter.observe(hud(20, 10), 0.2)["suggestion"] is None
    assert potter.observe(hud(20, 10), 2)["suggestion"] == "hp"


@pytest.mark.parametrize("issue", ["covered", "resize", "wrong_color", "unsafe"])
def test_uncertain_or_inactive_hud_cannot_suggest_a_potion(tmp_path, issue):
    potter = monitor(tmp_path)
    image = hud(20, 20)
    if issue == "covered":
        image[:] = 0
    elif issue == "resize":
        image = cv2.resize(image, (600, 200))
    elif issue == "wrong_color":
        image[31:45, 11:113] = (0, 210, 0)
    for now in [0, 0.1, 1]:
        assert potter.observe(image, now, safe=issue != "unsafe")["suggestion"] is None


def test_saved_settings_and_calibration_reload_without_starting_preview(tmp_path):
    potter = monitor(tmp_path)
    potter.configure(hp_threshold=65, mp_threshold=35, cooldown=2)
    loaded = PotionMonitor(potter.path)
    assert not loaded.enabled
    assert loaded.settings["hp_threshold"] == 65
    assert loaded.observe(hud(20), 0)["readings"]["hp"]["percent"] < 25
    assert loaded.observe(hud(20), 1)["suggestion"] is None
    assert list(tmp_path.glob("*.bak"))


def test_recovery_resets_confirmation_and_stop_disables_preview(tmp_path):
    potter = monitor(tmp_path)
    potter.observe(hud(20), 0)
    potter.observe(hud(), 0.1)
    assert potter.observe(hud(20), 0.2)["suggestion"] is None
    assert potter.observe(hud(20), 0.3)["suggestion"] == "hp"
    potter.stop()
    assert potter.observe(hud(20), 3)["suggestion"] is None


def test_non_bar_calibration_is_rejected(tmp_path):
    potter = PotionMonitor(tmp_path / "autopotter.json")
    with pytest.raises(ValueError):
        potter.calibrate("hp", np.zeros((100, 200, 3), dtype=np.uint8), Rect(10, 20, 100, 15))


def test_empty_hp_and_duplicate_timestamps_cannot_suggest(tmp_path):
    potter = monitor(tmp_path)
    assert potter.observe(hud(0, 10), 0)["suggestion"] is None
    assert potter.observe(hud(0, 10), 0.1)["suggestion"] is None
    assert "death" in potter.observe(hud(0, 10), 0.2)["reason"]
    potter.observe(hud(20), 1)
    assert potter.observe(hud(20), 1)["suggestion"] is None


@pytest.mark.parametrize("threshold", [-1, 100, float("nan")])
def test_invalid_thresholds_cannot_replace_saved_settings(tmp_path, threshold):
    potter = monitor(tmp_path)
    before = potter.path.read_bytes()
    with pytest.raises(ValueError):
        potter.configure(hp_threshold=threshold, mp_threshold=30, cooldown=1.5)
    assert potter.path.read_bytes() == before


def test_disabled_mp_does_not_block_hp_when_its_bar_is_unreadable(tmp_path):
    potter = monitor(tmp_path)
    potter.configure(hp_threshold=50, mp_threshold=0, cooldown=1.5)
    potter.start()
    image = hud(20)
    image[30:46, 150:254] = 0
    potter.observe(image, 0)
    assert potter.observe(image, 0.1)["suggestion"] == "hp"
