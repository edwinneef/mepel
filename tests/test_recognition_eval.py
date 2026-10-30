import pytest

from tools.recognition_eval import (
    Label,
    build_labels,
    coverage,
    score_frame,
    simulate_recovery,
)

ME = "nametag:me"


def record(sequence, at, template=ME, tracked=False, confidence=1.0, x=100):
    return {"sequence": sequence, "captured_at": at, "frame": f"{sequence}.png",
            "player": {"box": {"x": x, "y": 50, "width": 40, "height": 60},
                       "template": template, "tracked": tracked, "confidence": confidence}}


def segment(clip, first, last, **values):
    return {"clip": clip, "sequences": [first, last], "pose": "stand", "facing": "right",
            "occlusion": "none", **values}


def test_labels_cover_overlapping_clips_of_one_run_and_accept_reviewed_boxes():
    found = {"a": [record(1, 10.0), record(2, 10.1)],
             "b": [record(2, 10.1), record(3, 10.2, "tracked", True, 0.6)],
             "other": [record(2, 99.0)]}
    spec = {"identity": "me", "segments": [segment("a", 1, 3),
                                           segment("b", 3, 3, occlusion="player")]}
    labels, missing = build_labels(found, spec, 0.85)
    # Clip b shares frame 2 with clip a, so a's segment covers b's frames; "other" is a
    # different engine run with the same sequence numbers.
    assert missing == ["other/2.png"]
    assert labels["10.200"] == Label(None, "stand", "right", "player")
    assert labels["10.000"].box == (100, 50, 40, 60)

    spec["segments"][1]["box"] = "recorded"
    labels, _ = build_labels(found, spec, 0.85)
    assert labels["10.200"].box == (100, 50, 40, 60)

    with pytest.raises(ValueError):
        build_labels(found, {"identity": "me", "segments": [segment("a", 1, 3, pose="fly")]},
                     0.85)


def detection(template=ME, x=100, tracked=False, confidence=1.0):
    return {"box": (x, 50, 40, 60), "template": template, "tracked": tracked,
            "confidence": confidence}


def test_wrong_identity_means_another_tag_or_a_confirmed_tag_in_the_wrong_place():
    label = Label((100, 50, 40, 60), "walk", "left", "none")
    assert score_frame(label, detection(), ME, 0.85)["correct"]
    assert score_frame(label, detection(ME + ":tag-only"), ME, 0.85)["correct"]
    assert score_frame(label, detection("nametag:other"), ME, 0.85)["wrong_identity"]
    assert score_frame(label, detection(x=140), ME, 0.85)["wrong_identity"]
    sprite = score_frame(label, detection("sprite", x=140), ME, 0.85)
    assert sprite["sprite_only"] and not sprite["wrong_identity"] and not sprite["correct"]
    tracked = score_frame(label, detection("tracked", tracked=True, confidence=.6), ME, .85)
    assert not tracked["identified"] and tracked["error"] == 0


def frame(now, identity=ME, occlusion="none"):
    return {"now": now, "frame": f"{now}", "identified": identity is not None,
            "identity": identity, "occlusion": occlusion}


def test_recovery_resumes_on_two_spaced_fresh_frames_of_the_same_player():
    result = simulate_recovery([frame(0), frame(.1, None), frame(.2), frame(.4)])
    assert result == {"events": [{"result": "resumed", "frame": "0.1", "seconds": .3}],
                      "stopped": False}


def test_recovery_times_out_at_the_recorded_stop_and_judges_the_cover():
    frames = [frame(0), frame(.5, None, "player"), frame(1.0, ME, "player"),
              frame(1.5, None, "player")]
    assert simulate_recovery(frames)["events"][0]["result"] == "unfinished"
    stopped = simulate_recovery(frames, ended=2.6)
    assert stopped["stopped"]
    assert stopped["events"][-1] == {"result": "stopped", "reason": "timeout", "frame": "0.5",
                                     "seconds": 2.1, "justified": True}
    frames[3]["occlusion"] = "none"
    assert not simulate_recovery(frames, ended=2.6)["events"][-1]["justified"]


def test_recovery_stops_when_another_name_tag_appears():
    result = simulate_recovery([frame(0), frame(.1, None), frame(.2, "nametag:other")])
    assert result["stopped"] and result["events"][-1]["reason"] == "different_identity"


def scored(key, pose, correct, occlusion="none", template=ME, sprite=False):
    return {"key": key, "pose": pose, "facing": "right", "occlusion": occlusion,
            "correct": correct, "sprite_only": sprite, "error": 0, "template": template}


def test_coverage_needs_enough_uncovered_frames_recognized_in_every_replay():
    frames = [scored(str(i), "walk", True) for i in range(5)]
    frames += [scored(str(i), "walk", i != 0) for i in range(1)]  # second replay misses one
    frames += [scored(f"a{i}", "air", True) for i in range(4)]
    frames += [scored("c", "climb", False, "player"), scored("s", "walk", False, "tag",
                                                             "sprite", True)]
    result = coverage(frames)
    assert result["poses"]["walk/right"] == {"frames": 5, "correct": 4, "recall": .8,
                                             "verified": False}
    assert result["poses"]["air/right"]["verified"] is False  # only four frames
    assert "climb/right" not in result["poses"]
    assert result["verified"] == [] and "walk/right" in result["gaps"]
    assert result["templates"] == {"sprite": ["walk/right"]}
