from maplebot.moves import JUMP_RISE_PX, TAKEOFF_INSET_PX, _reach, generate


def flat(key, x0, x1, y):
    return {"id": key, "name": key, "start": {"x": x0, "y": y}, "end": {"x": x1, "y": y}}


def kinds(profile):
    return {(m.source, m.target): m.kind for m in generate(profile)}


def test_staircase_steps_jump_up_and_fall_back():
    profile = {"platforms": [flat("floor", 0, 1000, 500), flat("step", 300, 560, 440),
                             flat("high", 500, 800, 380)], "ropes": []}
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


def test_hairline_gap_is_walked_and_a_level_gap_is_beyond_a_jump_from_rest():
    profile = {"platforms": [flat("a", 0, 200, 300), flat("b", 220, 400, 300),
                             flat("c", 480, 600, 300), flat("low", 380, 600, 350)],
               "ropes": []}
    moves = kinds(profile)
    assert moves[("a", "b")] == "walk"
    # Taking off 48 px in, a level jump lands about 78 px out: short of c.
    assert ("b", "c") not in moves
    assert moves[("b", "low")] == "jump"  # falling off the end onto what runs on below


def test_supported_rope_top_uses_platform_before_upward_jump():
    rope = {"id": "rope", "start": {"x": 500, "y": 300},
            "end": {"x": 500, "y": 600}}
    profile = {"platforms": [flat("top", 400, 540, 300),
                             flat("higher", 500, 700, 240)], "ropes": [rope]}
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


def test_jumps_and_drops_take_off_with_room_to_brake_and_land_within_reach():
    profile = {"platforms": [flat("a", 0, 200, 300), flat("b", 220, 400, 300),
                             flat("low", 380, 600, 350), flat("tiny", 900, 990, 300),
                             flat("under", 850, 1100, 400), flat("src", 600, 850, 1025),
                             flat("dst", 794, 965, 972)], "ropes": []}
    moves = {(m.source, m.target): m for m in generate(profile)}
    assert moves[("a", "b")].trace[0] == (192.0, 300.0)  # walks still start at the end
    off_end = moves[("b", "low")]
    assert off_end.trace[0] == (400 - TAKEOFF_INSET_PX, 300.0)
    assert off_end.trace[-1][0] - off_end.trace[0][0] <= _reach(-50)
    up = moves[("src", "dst")]  # Tree Dungeon m_fh315_fh320 slid off from 24 px in
    assert up.trace[0][0] == 850 - TAKEOFF_INSET_PX
    assert 794 + 16 <= up.trace[-1][0] and up.trace[-1][0] - up.trace[0][0] <= _reach(53)
    # 90 px is too narrow to brake on from either side: no jump or drop leaves it.
    assert not [m for m in moves.values() if m.source == "tiny" and m.kind in {"jump", "drop"}]
    for move in moves.values():
        if move.kind in {"jump", "drop"} and move.source in {"b", "src", "under"}:
            left, right = {"b": (220, 400), "src": (600, 850), "under": (850, 1100)}[
                move.source]
            assert left + TAKEOFF_INSET_PX <= move.trace[0][0] <= right - TAKEOFF_INSET_PX


def test_reach_matches_the_jump_peak_and_the_proven_jump():
    assert _reach(JUMP_RISE_PX + 3) == 0  # above the 77 px peak
    assert 56 <= _reach(60) <= 64  # m_fh308_fh315 rose 60 px and covered 56-64 px
    assert _reach(-100) > _reach(0) > _reach(60)


def test_jump_traces_peak_where_a_jump_from_rest_peaks():
    # Live (Tree Dungeon, batch 4): the jump down fh320 -> fh315 rose to 80 px above its
    # launch; a trace peaking 30 px up left that apex 66 px outside the 64 px corridor.
    from maplebot.navigation_executor import distance

    profile = {"platforms": [flat("src", 600, 850, 1027), flat("dst", 794, 965, 973)],
               "ropes": []}
    down = {(m.source, m.target): m for m in generate(profile)}[("dst", "src")]
    apex = down.trace[1]
    assert down.trace[0][1] - apex[1] == 77
    assert distance((down.trace[0][0] - 20, down.trace[0][1] - 80), down.trace) < 64
