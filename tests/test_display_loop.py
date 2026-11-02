import time

import cv2
import numpy as np

from maplebot.display_loop import DisplayLoop, DisplaySource, DisplayTracks
from maplebot.geometry import Rect


def background():
    rng = np.random.default_rng(5)
    return cv2.GaussianBlur(rng.integers(60, 120, (768, 1366, 3), dtype=np.uint8), (0, 0), 6)


def sprite(seed):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (50, 40, 3), dtype=np.uint8)


def scene(actors):
    image = background()
    for (x, y), seed in actors:
        image[y:y + 50, x:x + 40] = sprite(seed)
    return image


def monster(x, y, name="Green Mushroom", frame="move-0"):
    return {"kind": "monster", "box": {"x": x, "y": y, "width": 40, "height": 50},
            "confidence": 1.0, "template": f"catalog:{name}:{frame}", "tracked": False}


def drawing(frame_id, captured_at, monsters, player=None, target=None):
    return {"frame": {"id": frame_id, "captured_at": captured_at}, "player": player,
            "monsters": monsters, "target": target, "position": None}


def test_recognition_ids_survive_display_and_hidden_diagnostics_remove_old_boxes():
    tracks = DisplayTracks()
    image = scene([((300, 300), 1)])
    known = {**monster(300, 300), "track_id": "enemy:17"}
    tracks.anchor(drawing("a", 1, [known]), image)
    assert tracks.items(1)[1][0]["track_id"] == "enemy:17"
    tracks.update(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1.1)
    hidden = drawing("b", 1.1, [])
    hidden["enemy_tracks"] = [{"track_id": "enemy:17", "state": "occluded"}]
    tracks.anchor(hidden, image)
    assert tracks.items(1.1)[1] == []


def test_boxes_outside_the_searched_window_survive_until_their_cell_is_searched():
    # A cell search found a far monster; the next results searched only near the player.
    tracks = DisplayTracks()
    image = scene([((300, 300), 1), ((1100, 300), 2)])
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    tracks.update(gray, 1.0)
    near = {**monster(300, 300), "track_id": "enemy:1"}
    far = {**monster(1100, 300, "Ribbon Pig"), "track_id": "enemy:2"}
    tracks.anchor(drawing("wide", 1.0, [near, far]), image)
    local = {"x": 0, "y": 90, "width": 700, "height": 420}
    for step, now in enumerate((1.2, 1.4, 1.6, 2.2, 2.9)):
        tracks.update(gray, now)
        result = drawing(f"local{step}", now, [near])
        result["enemy_tracks"] = [{"track_id": "enemy:2", "state": "lost"}]
        result["player_tracking"] = {"search": local}
        tracks.anchor(result, image)
        assert {item["track_id"] for item in tracks.items(now)[1]} == {"enemy:1", "enemy:2"}
    # A result whose enemy grid cell covered the far monster removes its box at once.
    tracks.update(gray, 2.95)
    tracks.anchor({**drawing("lost-cell", 2.95, [near]),
                   "enemy_tracks": [{"track_id": "enemy:2", "state": "lost"}],
                   "player_tracking": {"search": local,
                                       "enemy_cell": {"x": 900, "y": 200, "width": 400,
                                                      "height": 300}}}, image)
    assert {item["track_id"] for item in tracks.items(2.95)[1]} == {"enemy:1"}
    tracks.anchor(drawing("wide-again", 2.97, [near, far]), image)
    assert {item["track_id"] for item in tracks.items(2.97)[1]} == {"enemy:1", "enemy:2"}
    # A result that did search the whole frame also removes the box at once.
    tracks.update(gray, 3.0)
    full = drawing("full", 3.0, [near])
    full["enemy_tracks"] = [{"track_id": "enemy:2", "state": "lost"}]
    full["player_tracking"] = {"search": None}
    tracks.anchor(full, image)
    assert {item["track_id"] for item in tracks.items(3.0)[1]} == {"enemy:1"}


def test_enemy_diagnostics_follow_camera_without_becoming_fresh_evidence():
    from maplebot.display_loop import project_enemy_diagnostics

    image = np.random.default_rng(92).integers(0, 255, (300, 500, 3), dtype=np.uint8)
    shifted = cv2.warpAffine(image, np.float32([[1, 0, -15], [0, 1, 4]]), (500, 300))
    packet = drawing("a", 1, [])
    packet["enemy_tracks"] = [{"track_id": "enemy:1", "state": "occluded",
                               "predicted_position": [100, 150], "ground_position": [100, 150],
                               "visible_bounds": None, "observed": True}]
    moved = project_enemy_diagnostics(packet, image, shifted, 1.1)
    np.testing.assert_allclose(moved[0]["ground_position"], (85, 154), atol=1)
    assert not moved[0]["observed"]
    assert packet["enemy_tracks"][0]["observed"]  # Source packet remains image-paired.
    assert project_enemy_diagnostics(packet, image, shifted, 1.6) == []


def test_boxes_follow_image_motion_between_recognition_results_with_stable_ids():
    tracks = DisplayTracks()
    first = scene([((300, 300), 1), ((700, 320), 2)])
    tracks.update(cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), 10.0)
    tracks.anchor(drawing("a", 10.0, [monster(300, 300), monster(700, 320, "Ribbon Pig")],
                          target=monster(300, 300)), first)
    _, monsters, target = tracks.items(10.0)
    ids = {item["template"]: item["track_id"] for item in monsters}
    assert target["track_id"] == ids["catalog:Green Mushroom:move-0"]
    for step in range(1, 6):
        moved = scene([((300 + 6 * step, 300), 1), ((700 - 4 * step, 320), 2)])
        tracks.update(cv2.cvtColor(moved, cv2.COLOR_BGR2GRAY), 10.0 + step / 30)
    _, monsters, _ = tracks.items(10.0 + 5 / 30)
    boxes = {item["track_id"]: item["box"] for item in monsters}
    assert boxes[ids["catalog:Green Mushroom:move-0"]]["x"] == 330
    assert boxes[ids["catalog:Ribbon Pig:move-0"]]["x"] == 680
    # Recognition of the same species at the matching place keeps the display identity,
    # even when the animation frame differs.
    later = scene([((330, 300), 1), ((680, 320), 2)])
    tracks.anchor(drawing("b", 10.0 + 5 / 30, [monster(330, 300, frame="move-1"),
                                               monster(680, 320, "Ribbon Pig")]), later)
    assert {item["track_id"] for item in tracks.items(10.2)[1]} == set(ids.values())


def test_species_changes_and_ambiguous_neighbours_receive_new_ids():
    tracks = DisplayTracks()
    image = scene([((300, 300), 1), ((360, 300), 2)])
    tracks.anchor(drawing("a", 1.0, [monster(300, 300)]), image)
    old = tracks.items(1.0)[1][0]["track_id"]
    tracks.anchor(drawing("b", 1.1, [monster(300, 300, "Ribbon Pig")]), image)
    assert tracks.items(1.1)[1][0]["track_id"] != old
    tracks.anchor(drawing("c", 1.2, [monster(300, 300)]), image)
    single = tracks.items(1.2)[1][0]["track_id"]
    # Two equally plausible successors cannot inherit the identity.
    tracks.anchor(drawing("d", 1.3, [monster(290, 300), monster(310, 300)]), image)
    assert single not in {item["track_id"] for item in tracks.items(1.3)[1]}


def test_tracks_hide_without_image_support_and_expire_without_recognition():
    tracks = DisplayTracks()
    image = scene([((300, 300), 1)])
    tracks.anchor(drawing("a", 1.0, [monster(300, 300)],
                          player={**monster(600, 300), "kind": "player",
                                  "template": "nametag:x:tag-only"}), image)
    assert tracks.items(1.0)[0]["track_id"] == "player"
    blank = cv2.cvtColor(background(), cv2.COLOR_BGR2GRAY)
    tracks.update(blank, 1.2)
    assert len(tracks.items(1.2)[1]) == 1  # Briefly retained at the last confirmed place.
    tracks.update(blank, 1.6)
    assert tracks.items(1.6)[1] == []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    tracks.update(gray, 1.9)
    assert len(tracks.items(1.9)[1]) == 1
    tracks.update(gray, 3.1)  # Recognition has not confirmed it for over 2 seconds.
    assert tracks.tracks == {} and tracks.items(3.1) == (None, [], None)


def test_player_box_stays_on_recognition_and_ignores_scrolling_scenery():
    tracks = DisplayTracks()
    player = {**monster(600, 300), "kind": "player", "template": "nametag:x"}
    image = scene([((600, 300), 1)])
    tracks.update(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1.0)
    tracks.anchor(drawing("a", 0.9, [], player=player), image)
    # The camera scrolls: the scenery (and a sprite-like patch) moves 120 px. Patch matching
    # used to follow it; the player box stays where recognition put it.
    scrolled = np.roll(image, 120, axis=1)
    tracks.update(cv2.cvtColor(scrolled, cv2.COLOR_BGR2GRAY), 1.2)
    box = tracks.items(1.2)[0]["box"]
    assert (box["x"], box["y"]) == (600, 300)
    moved = {**player, "box": {**player["box"], "x": 640, "y": 260}}
    tracks.anchor(drawing("b", 1.15, [], player=moved), scrolled)
    box = tracks.items(1.25)[0]["box"]
    assert (box["x"], box["y"]) == (640, 260)
    tracks.update(cv2.cvtColor(scrolled, cv2.COLOR_BGR2GRAY), 1.9)
    assert tracks.items(1.9)[0] is None  # no recognition for over VISIBLE seconds


def test_late_recognition_refreshes_boxes_before_they_expire():
    # Recognition arrives about 0.5 s after its capture, every 0.55 s.
    tracks = DisplayTracks()
    image = scene([((300, 300), 1)])
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    arrivals = [1.5, 2.05, 2.6, 3.15]
    shown = []
    for step in range(int(1.5 * 30), int(3.4 * 30)):
        now = step / 30
        tracks.update(gray, now)
        while arrivals and arrivals[0] <= now:
            arrival = arrivals.pop(0)
            item = {**monster(300, 300), "track_id": "enemy:1"}
            tracks.anchor(drawing(f"r{arrival}", arrival - .52, [item]), image)
        shown.append(len(tracks.items(now)[1]))
    assert shown and all(count == 1 for count in shown)


def test_an_animating_sprite_keeps_pace_at_recognition_speed():
    # Ever-changing animation frames defeat patch matching, as a hopping slime does.
    # Recognition (every 0.25 s, arriving 0.2 s late) measures its 90 px/s walk.
    tracks = DisplayTracks()

    def truth(t):
        return 200 + 90 * t

    def frame(t):
        return scene([((round(truth(t)), 300), 10 + int(t * 7))])

    pending = [(c / 4 + .2, c / 4) for c in range(16)]
    errors = []
    for step in range(int(4 * 30)):
        now = step / 30
        tracks.update(cv2.cvtColor(frame(now), cv2.COLOR_BGR2GRAY), now)
        while pending and pending[0][0] <= now:
            _, captured = pending.pop(0)
            item = {**monster(round(truth(captured)), 300), "track_id": "enemy:1"}
            tracks.anchor(drawing(f"r{captured}", captured, [item]), frame(captured))
        if now >= .75:
            drawn = tracks.items(now)[1]
            assert drawn, now
            errors.append(abs(drawn[0]["box"]["x"] - truth(now)))
    assert np.median(errors) <= 10 and max(errors) <= 40


class FakeCapture:
    def __init__(self, frames):
        self.frames = frames

    def window(self, hwnd, calibration):
        return self.frames.pop(0), None, None

    def grab(self, region):
        return self.frames.pop(0)

    def close(self):
        pass


def test_loop_packets_are_display_only_latest_and_reset_on_source_change():
    image = scene([((300, 300), 1)])
    now = time.time()
    anchor = drawing("s:1", now, [monster(300, 300)])
    sources = [DisplaySource("s:source:0", 0, 7, None, None, (anchor, image), None)]
    loop = DisplayLoop(lambda: sources[-1], 30)
    packet = loop.step(FakeCapture([image]))
    assert packet["display"] is True and packet["terrain"] is None
    assert packet["frame"]["source_id"] == "s:source:0" and packet["frame"]["width"] == 1366
    assert packet["monsters"][0]["track_id"] == "monster:1"
    assert packet["anchor"]["id"] == "s:1"
    # A source change while capturing discards that frame and every track.
    capture = FakeCapture([image])
    original = capture.window

    def changed(hwnd, calibration):
        sources.append(DisplaySource("s:source:1", 1, 7, None, None, (anchor, image), None))
        return original(hwnd, calibration)

    capture.window = changed
    assert loop.step(capture) is None and loop.tracks.tracks == {}
    sources.append(DisplaySource("s:source:1", 1, 7, None, None, None, None))
    assert loop.step(FakeCapture([image])) is None


def test_loop_publishes_terrain_alignment_and_captures_only_on_demand():
    reference = background()
    rng = np.random.default_rng(3)
    for _ in range(600):
        x, y = rng.integers([0, 0], [1366, 768])
        cv2.circle(reference, (int(x), int(y)), int(rng.integers(3, 10)),
                   tuple(int(v) for v in rng.integers(30, 255, 3)), -1)
    anchor = drawing("s:1", time.time(), [])
    source = DisplaySource("s:source:0", 0, None, Rect(0, 0, 1366, 768), None,
                           (anchor, reference), ("area", 3, reference, 0.0, 0.0, 1.0))
    loop = DisplayLoop(lambda: source, 30)
    packet = loop.step(FakeCapture([reference.copy()]))
    assert packet["terrain"]["alignment"]["valid"] is True
    assert packet["terrain"]["area_id"] == "area"
    assert packet["terrain"]["projection"]["revision"] == 3
    assert abs(packet["terrain"]["projection"]["x"]) < 1
    created = []
    loop = DisplayLoop(lambda: source, 60, capture_factory=lambda: created.append(1) or FakeCapture(
        [reference.copy() for _ in range(500)]))
    loop.start()
    try:
        time.sleep(0.15)
        assert created == [] and loop.drawings() is None
        deadline = time.monotonic() + 2
        while loop.drawings() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert loop.drawings()["display"] is True and created == [1]
    finally:
        loop.close()


def test_confident_matches_follow_gradual_animation_until_recognition_returns():
    tracks = DisplayTracks()
    start, end = sprite(1).astype(float), sprite(9).astype(float)
    image = background()
    image[300:350, 300:340] = sprite(1)
    tracks.anchor(drawing("a", 1.0, [monster(300, 300)]), image)
    for step in range(1, 13):
        frame = background()
        mix = step / 12
        frame[300:350, 300 + 3 * step:340 + 3 * step] = (start * (1 - mix) + end * mix).astype(
            np.uint8)
        tracks.update(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.0 + step / 30)
    # The final appearance shares nothing with the anchor patch, yet the box kept up.
    assert tracks.items(1.4)[1][0]["box"]["x"] == 336


def test_late_recognition_never_snaps_a_tracked_box_back_and_misses_keep_ids():
    tracks = DisplayTracks()
    first = scene([((300, 300), 1), ((700, 300), 2)])
    tracks.update(cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), 1.0)
    tracks.anchor(drawing("a", 1.0, [monster(300, 300), monster(700, 300, "Ribbon Pig")]), first)
    ids = [item["track_id"] for item in tracks.items(1.0)[1]]
    for step in range(1, 13):
        frame = scene([((300 + 5 * step, 300), 1), ((700, 300), 2)])
        tracks.update(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.0 + step / 30)
    # Recognition of a frame 0.2 s old places the mushroom 20 px behind its live box,
    # and misses the pig once.
    old = scene([((340, 300), 1), ((700, 300), 2)])
    tracks.anchor(drawing("b", 1.0 + 8 / 30, [monster(340, 300, frame="move-1")]), old)
    _, monsters, _ = tracks.items(1.4)
    boxes = {item["track_id"]: item["box"]["x"] for item in monsters}
    assert boxes == {ids[0]: 360, ids[1]: 700}
