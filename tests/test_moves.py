from maplebot.moves import JUMP_RISE_PX, generate


def flat(key, x0, x1, y):
    return {"id": key, "name": key, "start": {"x": x0, "y": y}, "end": {"x": x1, "y": y}}


def kinds(profile):
    return {(m.source, m.target): m.kind for m in generate(profile)}


def test_staircase_steps_jump_up_and_fall_back():
    profile = {"platforms": [flat("floor", 0, 1000, 500), flat("step", 300, 450, 440),
                             flat("high", 430, 600, 380)], "ropes": []}
    moves = kinds(profile)
    assert moves[("floor", "step")] == "jump" and moves[("step", "high")] == "jump"
    assert moves[("step", "floor")] in {"jump", "drop"}
    assert moves[("high", "step")] in {"jump", "drop"}
    assert ("floor", "high") not in moves  # 120 px is beyond one jump


def test_drop_lands_on_the_first_platform_below():
    profile = {"platforms": [flat("floor", 0, 1000, 600), flat("mid", 200, 800, 450),
                             flat("top", 300, 700, 300)], "ropes": []}
    moves = generate(profile)
    drops = {(m.source, m.target) for m in moves if m.kind == "drop"}
    assert ("top", "mid") in drops and ("mid", "floor") in drops
    assert ("top", "floor") not in drops  # the middle platform is in the way


def test_hairline_gap_is_walked_and_wide_gap_is_jumped():
    profile = {"platforms": [flat("a", 0, 200, 300), flat("b", 220, 400, 300),
                             flat("c", 480, 600, 300), flat("far", 800, 900, 300)], "ropes": []}
    moves = kinds(profile)
    assert moves[("a", "b")] == "walk" and moves[("b", "c")] == "jump"
    assert ("c", "far") not in moves


def test_supported_rope_top_uses_platform_before_upward_jump():
    rope = {"id": "rope", "start": {"x": 500, "y": 300},
            "end": {"x": 500, "y": 600}}
    profile = {"platforms": [flat("top", 460, 540, 300),
                             flat("higher", 570, 700, 240)], "ropes": [rope]}
    pairs = kinds(profile)
    assert pairs[("rope", "top")] == "climb"
    assert ("rope", "higher") not in pairs
    assert pairs[("top", "higher")] == "jump"


def test_ropes_connect_their_foot_top_and_neighbours():
    rope = {"id": "rope", "name": "Rope", "start": {"x": 500, "y": 292},
            "end": {"x": 500, "y": 608}}
    profile = {"platforms": [flat("floor", 0, 1000, 600), flat("top", 450, 700, 300),
                             flat("side", 300, 440, 450)], "ropes": [rope]}
    moves = generate(profile)
    pairs = {(m.source, m.target): m for m in moves}
    for pair in (("floor", "rope"), ("rope", "floor"), ("rope", "top"), ("top", "rope"),
                 ("side", "rope")):
        assert pairs[pair].kind == "climb"
    assert pairs[("rope", "side")].kind == "jump"
    assert pairs[("floor", "rope")].trace == ((500, 600), (500, 570), (500, 562), (500, 554),
                                             (500, 546))


def test_rope_foot_within_a_jump_is_reached_by_jumping():
    rope = {"id": "rope", "name": "Rope", "start": {"x": 500, "y": 200},
            "end": {"x": 500, "y": 600 - JUMP_RISE_PX + 5}}
    profile = {"platforms": [flat("floor", 0, 1000, 600)], "ropes": [rope]}
    assert kinds(profile) == {("floor", "rope"): "climb"}


def test_jumps_off_an_end_take_off_well_inside_it():
    profile = {"platforms": [flat("a", 0, 200, 300), flat("b", 220, 400, 300),
                             flat("c", 480, 600, 300), flat("low", 620, 700, 400),
                             flat("tiny", 900, 930, 300)], "ropes": []}
    moves = {(m.source, m.target): m for m in generate(profile)}
    assert moves[("a", "b")].trace[0] == (192.0, 300.0)  # walks still start at the end
    assert moves[("b", "c")].trace[0] == (376.0, 300.0)  # level jump: 24 px from the end
    assert moves[("c", "low")].trace[0] == (576.0, 300.0)  # fall off the end
    tiny = [m for m in moves.values() if m.source == "tiny" and m.kind == "jump"]
    assert all(915 - 15 <= m.trace[0][0] <= 915 + 15 for m in tiny)  # narrow: centre
