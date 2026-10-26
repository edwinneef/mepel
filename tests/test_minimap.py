import json
import runpy
from pathlib import Path

import cv2
import numpy as np
import pytest

from maplebot.minimap import DOT_SHAPE, MinimapDetector, MinimapReading, terrain_motion


def screenshot(dot=(40, 30)):
    image = np.zeros((766, 1023, 3), np.uint8)
    rng = np.random.default_rng(12)
    image[2:16, 3:60] = rng.integers(0, 255, (14, 57, 3), dtype=np.uint8)
    image[68, 3:220] = 255
    image[136, 3:220] = 255
    terrain = rng.integers(10, 100, (66, 212), dtype=np.uint8)
    image[70:136, 5:217] = np.repeat(terrain[:, :, None], 3, axis=2)
    if dot:
        x, y = dot[0] + 5, dot[1] + 70
        image[y:y + 6, x:x + 6][DOT_SHAPE] = (0, 255, 255)
    return image


def test_unique_marker_and_panel_are_measured_without_modifying_pixels():
    image = screenshot()
    original = image.copy()
    reading = MinimapDetector(image).read(image)
    assert reading.dot == (42.5, 32.5)
    assert reading.candidates == 1
    assert reading.canvas.shape == (66, 212, 3)
    np.testing.assert_array_equal(image, original)


def test_multiple_yellow_markers_are_not_resolved_using_the_name_track():
    image = screenshot()
    detector = MinimapDetector(image)
    image[100:106, 100:106][DOT_SHAPE] = (0, 255, 255)
    reading = detector.read(image)
    assert reading.candidates == 2
    assert reading.dot is None


def test_yellow_scenery_and_clipped_components_do_not_become_player_dots():
    image = screenshot()
    detector = MinimapDetector(image)
    cv2.circle(image, (100, 100), 3, (0, 255, 255), -1)  # 7x7 terrain decoration.
    image[110:116, 214:220][DOT_SHAPE] = (0, 255, 255)  # Clipped by the minimap edge.
    assert detector.read(image).dot == (42.5, 32.5)


def test_marker_loss_header_occlusion_and_bad_capture_size_stay_unknown():
    detector = MinimapDetector(screenshot())
    assert detector.read(screenshot(None)).dot is None
    covered = screenshot()
    covered[:50] = 0
    assert detector.read(covered).reason == "Minimap header missing or covered"
    assert detector.read(np.zeros((15, 106, 3), np.uint8)).reason == "Unsupported capture size"
    with pytest.raises(ValueError, match="1023x766"):
        MinimapDetector(covered[:100])


def test_terrain_registration_handles_scroll_and_moving_dot_separately():
    detector = MinimapDetector(screenshot())
    original = detector.read(screenshot()).canvas
    moved = cv2.warpAffine(original, np.float32([[1, 0, 3], [0, 1, -2]]), (212, 66))
    cv2.circle(moved, (110, 40), 3, (0, 255, 255), -1)
    shift, quality = terrain_motion(original, moved)
    assert shift == (3, -2)
    assert quality > 0.9
    assert terrain_motion(np.zeros_like(original), np.zeros_like(original))[1] == 0
    assert terrain_motion(original, original[:20])[1] == 0


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[1] / "tools/minimap_probe.py"
    return runpy.run_path(str(path))


def row(index, *, dot=None, feet=None, camera=(0, 0), named=True):
    return {
        "time": index * 0.3, "sequence": index, "capture_id": index,
        "frame": f"{index:08d}.png", "named": named,
        "feet": np.array(feet if feet is not None else (100 + index * 32, 100)),
        "camera": np.array(camera), "camera_confidence": 1,
        "reading": MinimapReading(dot or (40 + index * 2, 30),
                                  screenshot()[70:136, 5:217].copy(), 1, "ok"),
    }


def test_scale_is_fit_on_separate_six_frame_motion_blocks(probe):
    calibration = probe["fit_scale"]([row(index) for index in range(19)])
    assert calibration["pixels_per_minimap_pixel"] == pytest.approx(16)
    assert len(calibration["six_frame_estimates"]) == 3
    with pytest.raises(ValueError, match="Calibration needs"):
        probe["fit_scale"]([row(0), row(1)])


def test_name_motion_cross_check_accounts_for_camera_motion_and_rejects_wrong_dot(probe):
    rows = [row(0), row(1, feet=(100, 100), camera=(-32, 0)),
            row(2, dot=(90, 30), feet=(100, 100))]
    metrics, results = probe["validate"](rows, 16)
    assert metrics["unique_dot_frames"] == 3
    assert metrics["checkable_frames"] == 2
    assert metrics["aligned_frames"] == 1
    assert results[1]["aligned"]
    assert results[2]["reason"] == "Motion disagrees"
    assert metrics["accuracy"] is None
    assert metrics["input_sent"] is False


@pytest.mark.parametrize("problem", ["name", "dot", "camera", "time", "sequence", "png"])
def test_missing_cross_check_evidence_is_not_counted_as_alignment(probe, problem):
    first, second = row(0), row(1)
    if problem == "name":
        second["named"] = False
    elif problem == "dot":
        second["reading"] = MinimapReading(None, second["reading"].canvas, 2, "ambiguous")
    elif problem == "camera":
        second["camera_confidence"] = 0
    elif problem == "time":
        second["time"] = 5
    elif problem == "sequence":
        second["sequence"] = 4
    else:
        second["reading"] = None
    assert probe["validate"]([first, second], 16)[0]["aligned_frames"] == 0


def test_cli_keeps_calibration_separate_and_does_not_modify_sources(probe, tmp_path, monkeypatch):
    root = tmp_path / "recordings"
    for session, count, clock in [(probe["CALIBRATION"], 19, 0), (probe["BASELINE"], 3, 100)]:
        folder = root / session
        folder.mkdir(parents=True)
        records = []
        for index in range(count):
            name = f"{index:08d}.png"
            cv2.imwrite(str(folder / name), screenshot((40 + index * 2, 30)))
            records.append({
                "frame": name, "sequence": index, "captured_at": clock + index * 0.3,
                "policy_input": {"now": index * 0.3},
                "camera_shift": [0, 0], "camera_confidence": 1,
                "player": {"template": "nametag:example", "confidence": 1, "box": {
                    "x": 95 + index * 32, "y": 80, "width": 10, "height": 20,
                }},
            })
        (folder / "decisions.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
        )
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    output = tmp_path / "output"
    monkeypatch.setattr("sys.argv", [
        "minimap_probe", str(root), "--reference",
        str(root / probe["BASELINE"] / "00000000.png"), "--output", str(output),
    ])
    probe["main"]()
    summary = json.loads((output / "summary.json").read_text())
    baseline = next(r for r in summary["recordings"] if r["recording"] == probe["BASELINE"])
    assert baseline["aligned_frames"] == 2
    assert baseline["calibration_overlap_frames"] == 0
    assert summary["calibration"]["pixels_per_minimap_pixel"] == pytest.approx(16)
    after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert after == before
    with pytest.raises(ValueError, match="new output directory"):
        probe["main"]()
