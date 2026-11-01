import cv2
import numpy as np

from maplebot.structure_detection import detect


def scene():
    image = np.zeros((768, 1366, 3), np.uint8)
    cv2.line(image, (600, 260), (600, 520), (220, 220, 220), 3)
    cv2.line(image, (640, 260), (640, 520), (220, 220, 220), 3)
    for y in range(270, 515, 18):
        cv2.line(image, (600, y), (640, y), (220, 220, 220), 3)
    cv2.line(image, (450, 550), (1000, 550), (200, 200, 200), 3)
    return image


def test_shared_detector_finds_ladder_axis_and_uncertain_surface():
    found = detect(scene())
    assert any(s.kind == "ladder" and abs(s.coordinate - 620) <= 4 for s in found)
    assert any(s.kind == "surface" and abs(s.coordinate - 550) <= 4
               and s.uncertainty >= 8 for s in found)


def test_hud_actor_and_blank_pixels_cannot_be_structure_evidence():
    assert detect(np.zeros((768, 1366, 3), np.uint8)) == []
    assert not any(s.kind == "ladder" for s in detect(
        scene(), [{"x": 580, "y": 250, "width": 80, "height": 290}]))
    image = np.zeros((768, 1366, 3), np.uint8)
    image[:200, :300] = scene()[250:450, 500:800]
    assert detect(image) == []


def test_oversized_or_wrong_format_capture_refuses_without_guessing():
    assert detect(np.zeros((768, 1366), np.uint8)) == []
    assert detect(np.zeros((1300, 2200, 3), np.uint8)) == []


def test_glowing_portal_is_only_an_uncertain_visual_candidate():
    image = np.zeros((768, 1366, 3), np.uint8)
    cv2.ellipse(image, (700, 400), (24, 60), 0, 0, 360, (255, 200, 0), -1)
    portals = [s for s in detect(image) if s.kind == "portal"]
    assert len(portals) == 1 and abs(portals[0].coordinate - 700) <= 1
    assert portals[0].uncertainty >= 8
