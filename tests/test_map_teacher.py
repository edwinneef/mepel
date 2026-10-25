import pytest

from maplebot.geometry import Rect
from maplebot.localization import MinimapTransform
from maplebot.map_teacher import MapTeacher
from maplebot.minimap_reader import MinimapFix
from maplebot.perception import Detection


def fix(x, y):
    return MinimapFix((x, y), Rect(0, 0, 100, 60), 1.0, 1, "Player marker on the taught map")


def tag(feet_y):
    return Detection("player", Rect(0, feet_y - 64, 44, 64), 1.0, "nametag")


def play(path):
    """path: (dot x, dot y, screen feet y) per frame, 0.2 s apart, camera still."""
    teacher = MapTeacher(MinimapTransform(16, 0, 16, 0))
    for index, (x, y, feet) in enumerate(path):
        teacher.add(fix(x, y), tag(feet), (0, 0), index * 0.2)
    return teacher.geometry()


def test_walk_climb_ledge_and_drop_become_platforms_rope_and_directed_links():
    path = [(x, 40, 600) for x in range(10, 31)]
    path += [(30, y, 600 - 16 * (40 - y)) for y in range(39, 31, -1)]
    path += [(x, 32, 472) for x in range(30, 46)]
    path += [(45 + step, 32 + step, 472 + 16 * step) for step in range(1, 9)]
    path += [(x, 40, 600) for x in range(53, 61)]
    geometry = play(path)
    heights = sorted((p["start"]["y"], p["start"]["x"], p["end"]["x"])
                     for p in geometry["platforms"])
    assert heights == [(512, 472, 728), (640, 168, 488), (640, 840, 968)]
    [rope] = geometry["ropes"]
    assert rope["start"]["x"] == rope["end"]["x"] == 480
    assert rope["start"]["y"] <= 528 and rope["end"]["y"] >= 608
    names = {p["id"]: (p["start"]["y"], p["start"]["x"]) for p in geometry["platforms"]}
    names[rope["id"]] = "rope"
    links = {(names[link["from"]], names[link["to"]], link["kind"]) for link in geometry["links"]}
    assert links == {
        ((640, 168), "rope", "climb"), ("rope", (512, 472), "climb"),
        ((512, 472), (640, 840), "drop"),
    }
    boundary = geometry["boundary"]
    assert boundary["x"] <= 168 and boundary["x"] + boundary["width"] >= 968
    assert boundary["y"] <= 412 and boundary["y"] + boundary["height"] >= 640


def test_straight_jump_is_not_a_rope_and_a_hop_keeps_one_floor():
    path = [(x, 40, 600) for x in range(10, 21)]
    path += [(20, 38, 568), (20, 36, 536), (20, 38, 568)]
    path += [(x, 40, 600) for x in range(20, 25)]
    path += [(26, 38, 568), (29, 37, 552), (32, 38, 568)]
    path += [(x, 40, 600) for x in range(34, 40)]
    geometry = play(path)
    assert geometry["ropes"] == [] and geometry["links"] == []
    [floor] = geometry["platforms"]
    assert (floor["start"]["x"], floor["end"]["x"]) == (168, 632)


def test_marker_loss_and_shaky_name_tag_record_nothing_as_ground():
    teacher = MapTeacher(MinimapTransform(16, 0, 16, 0))
    for index in range(10):
        dot = MinimapFix(None, None, 0.0, 0, "Minimap missing") if index % 2 else fix(index, 40)
        teacher.add(dot, tag(600 + 10 * index), (0, 0), index * 0.2)
    assert teacher.geometry()["platforms"] == []
    with pytest.raises(ValueError):
        MinimapTransform(0, 0, 0, 0)
