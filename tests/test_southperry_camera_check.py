import numpy as np

from tools.check_southperry_camera import landmark, reference


def test_landmark_rejects_repeated_identical_candidates():
    rng = np.random.default_rng(25)
    pixels = rng.integers(0, 256, (18, 20, 3), dtype="uint8")
    sprite = np.dstack((pixels, np.full((18, 20), 255, "uint8")))
    frame = rng.integers(0, 256, (100, 160, 3), dtype="uint8")
    frame[35:53, 20:40] = pixels
    assert landmark(frame, sprite, .65)["accepted"]
    frame[35:53, 95:115] = pixels
    assert not landmark(frame, sprite, .65)["accepted"]


def test_blank_scene_does_not_create_a_landmark():
    rng = np.random.default_rng(26)
    sprite = rng.integers(1, 256, (18, 20, 4), dtype="uint8")
    sprite[:, :, 3] = 255
    assert not landmark(np.zeros((100, 160, 3), "uint8"), sprite, .65)["accepted"]


def test_reference_requires_two_accepted_agreeing_landmarks():
    origins = {"house": [-403, -92], "house-decoration": [-374, 74]}
    rows = {"house": {"accepted": True, "top_left": [249, 167]},
            "house-decoration": {"accepted": True, "top_left": [278, 333]}}
    assert reference(rows, origins).tolist() == [652, 259]
    rows["house-decoration"]["top_left"][0] += 4
    assert reference(rows, origins) is None
    rows["house-decoration"]["accepted"] = False
    assert reference(rows, origins) is None
