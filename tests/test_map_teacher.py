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
    path += [(45 + step, 32 + 2 * step, 472 + 32 * step) for step in range(1, 5)]
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


def test_walking_a_slope_makes_one_sloped_platform_and_reports_route_problems():
    path = [(x, 40, 600) for x in range(10, 20)]
    for step, x in enumerate(range(20, 30)):
        path.append((x, 40 - (step + 1) // 2, 600))  # one marker pixel up every second step
    path += [(x, 35, 600) for x in range(30, 40)]
    geometry = play(path)
    [ramp] = geometry["platforms"]
    assert ramp["start"]["y"] > ramp["end"]["y"]  # higher on the right
    assert geometry["problems"] == {"home": ramp["id"], "unreachable": [], "stranded": []}


def test_problems_list_unreachable_and_stranded_surfaces():
    from maplebot.map_teacher import problems

    flat = [{"id": key, "start": {"x": 0, "y": y}, "end": {"x": width, "y": y}}
            for key, y, width in (("floor", 600, 900), ("ledge", 400, 200), ("island", 300, 100))]
    links = [{"id": "l1", "from": "floor", "to": "ledge", "kind": "jump"}]
    assert problems(flat, [], links) == {
        "home": "floor", "unreachable": ["island"], "stranded": ["ledge"],
    }


def test_home_is_the_widest_floor_despite_sub_pixel_height_noise():
    from maplebot.map_teacher import problems

    floors = [{"id": key, "start": {"x": x, "y": y}, "end": {"x": x + width, "y": y}}
              for key, x, y, width in (("main", 298, 1510.2, 1343), ("side", 1934, 1510.3, 294),
                                       ("ledge", 0, 1490, 2000))]
    assert problems(floors, [], [])["home"] == "main"


def test_restore_moves_the_check_log_with_its_samples():
    teacher = MapTeacher(MinimapTransform(16, 0, 16, 0))
    for index, x in enumerate(range(10, 20)):
        teacher.add(fix(x, 40), tag(600), (0, 0), 50_000 + index * 0.2)
    restored = MapTeacher.restore(teacher.checkpoint())
    assert restored.samples[0].t != teacher.samples[0].t
    sampled = {sample.t for sample in restored.samples}
    assert sampled <= {row["t"] for row in restored.log}


def test_level_marker_counts_as_standing_without_a_camera_estimate():
    teacher = MapTeacher(MinimapTransform(16, 0, 16, 0))
    for index, x in enumerate(range(10, 30)):
        teacher.add(fix(x, 40), tag(600), None, index * 0.3)
    [floor] = teacher.geometry()["platforms"]
    assert (floor["start"]["x"], floor["end"]["x"]) == (168, 472)


def test_trapezoid_ends_bend_the_platform_while_flat_walks_stay_straight():
    from maplebot.map_teacher import surface_y

    path = [(x, 40, 600) for x in range(10, 50)]  # long flat top
    path += [(50 + step, 41 + step, 600) for step in range(6)]  # sloped right end
    geometry = play(path)
    [ledge] = geometry["platforms"]
    assert len(ledge["points"]) >= 3
    for x, y in [(15, 40), (45, 40), (52, 43), (55, 46)]:
        assert abs(surface_y(ledge, x * 16) - y * 16) <= 12
    assert abs(ledge["end"]["y"] - 46 * 16) > 12  # the straight line misses the slope
    [flat] = play([(x, 40, 600) for x in range(10, 60)])["platforms"]
    assert "points" not in flat
