from dataclasses import replace

import pytest

from maplebot.config import AgentConfig
from maplebot.decision import Agent, PolicyInput, State
from maplebot.enemy_tracking import EnemyTrack
from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation


def entity(kind="monster", x=200, y=100, confidence=0.99):
    return Detection(kind, Rect(x, y, 24, 28), confidence)


def scene(monsters=None, player=None, shift=(0, 0)):
    return Observation(
        player or entity("player", 100),
        monsters if monsters is not None else [entity()],
        camera_shift=shift,
    )


def test_selects_nearest_same_platform_and_moves_in_short_steps():
    agent = Agent(AgentConfig())
    agent.start()
    targets = [entity(x=120, y=30), entity(x=250), entity(x=200)]
    acquired = agent.step(scene(targets), 0)
    assert acquired.state == State.APPROACH
    assert acquired.target.box.x == 200
    movement = agent.step(scene(targets), 0.1)
    assert movement.action.kind == "right"
    assert movement.action.seconds == 0.12


def test_ranged_attack_faces_and_fires_without_melee_approach():
    agent = Agent(AgentConfig(attack_min_range=80, attack_range=300))
    agent.start()
    target = scene([entity(x=350)])
    agent.step(target, 0)
    facing = agent.step(target, 0.1)
    assert facing.state == State.ATTACK and facing.action.kind == "right"
    assert agent.step(target, 0.2).action.kind == "attack"


def test_ranged_target_enters_dead_zone_before_firing():
    agent = Agent(AgentConfig(attack_min_range=80, attack_range=300))
    agent.start()
    target = scene([entity(x=190)])
    agent.step(target, 0)
    agent.step(target, 0.1)
    result = agent.step(scene([entity(x=170)]), 0.2)
    assert result.state == State.IDLE and result.action.kind == "release"
    assert "minimum attack range" in result.reason


def test_target_crossing_sides_requires_facing_again():
    agent = Agent(AgentConfig())
    agent.start()
    target = scene([entity(x=120)])
    agent.step(target, 0)
    agent.step(target, 0.1)
    result = agent.step(scene([entity(x=80)]), 0.2)
    assert result.state == State.ATTACK and result.action.kind == "left"


@pytest.mark.parametrize("low,high", [(-1, 65), (65, 65), (70, 65), (0, float('inf')),
                                       (float('nan'), 65)])
def test_rejects_invalid_attack_range(low, high):
    with pytest.raises(ValueError, match="attack_min_range"):
        AgentConfig(attack_min_range=low, attack_range=high)


@pytest.mark.parametrize("x,direction", [(0, "left"), (220, "right")])
def test_moves_towards_target(x, direction):
    agent = Agent(AgentConfig())
    agent.start()
    observation = scene([entity(x=x)])
    agent.step(observation, 0)
    assert agent.step(observation, 0.1).action.kind == direction


@pytest.mark.parametrize("direction,far_x,near_x", [("left", 0, 50), ("right", 220, 150)])
def test_completed_approach_attacks_on_first_clear_in_range_frame(direction, far_x, near_x):
    agent = Agent(AgentConfig())
    agent.start()
    agent.step(scene([entity(x=far_x)]), 0)
    assert agent.step(scene([entity(x=far_x)]), .1).action.kind == direction
    outcome = {"status": "completed", "action": direction, "result": f"{direction} completed"}
    decision = agent.step_input(PolicyInput(scene([entity(x=near_x)]), .3, outcome, 100))
    assert decision.action.kind == "skill" and decision.state == State.VERIFY
    assert agent.attempts == 1


@pytest.mark.parametrize("outcome", [
    {"status": "pending", "ticket": 1},
    {"status": "not_sent"},
    {"status": "completed", "action": "left", "result": "left interrupted"},
    {"status": "completed", "action": "right", "result": "right completed"},
    {"status": "completed", "action": "hp_potion", "result": "hp_potion completed"},
])
def test_unconfirmed_or_wrong_direction_approach_still_faces_before_attack(outcome):
    agent = Agent(AgentConfig())
    agent.start()
    agent.step(scene([entity(x=0)]), 0)
    agent.step(scene([entity(x=0)]), .1)
    decision = agent.step_input(PolicyInput(scene([entity(x=50)]), .3, outcome, 100))
    assert decision.action.kind == "left" and decision.state == State.ATTACK
    assert agent.attempts == 0


def test_attack_is_followed_by_observation_and_no_kill_claim():
    agent = Agent(AgentConfig())
    agent.start()
    close = scene([entity(x=140)])
    assert agent.step(close, 0).state == State.APPROACH
    facing = agent.step(close, 0.1)
    assert facing.state == State.ATTACK
    assert facing.action.kind == "right"
    attack = agent.step(close, 0.2)
    assert attack.state == State.VERIFY
    assert attack.action.kind == "attack"
    assert agent.step(close, 0.3).action.kind == "release"
    absent = scene([])
    assert agent.step(absent, 0.8).state == State.VERIFY
    assert agent.step(absent, 0.9).state == State.VERIFY
    result = agent.step(absent, 1.0)
    assert result.state == State.SEARCH
    assert result.action.kind == "release"
    assert "kill unconfirmed" in result.reason


@pytest.mark.parametrize(
    "observation",
    [
        Observation(None, [entity()]),
        scene(player=entity("player", 100, confidence=0.4)),
    ],
)
def test_uncertainty_stops_and_releases(observation):
    agent = Agent(AgentConfig())
    agent.start()
    decision = agent.step(observation, 0)
    assert decision.state == State.IDLE
    assert decision.action.kind == "release"


@pytest.mark.parametrize("observation", [scene([entity(confidence=0.826133)]),
                                        scene([]), scene([entity(y=30)])])
def test_no_target_waits_without_movement_until_a_fresh_target_or_explicit_stop(observation):
    agent = Agent(AgentConfig())
    agent.start()
    for now in (10, 10.5, 11.99, 100):
        decision = agent.step(observation, now)
        assert decision.state == State.SEARCH
        assert decision.action.kind == "release"
    restored = Agent(AgentConfig())
    restored.restore(agent.snapshot())
    assert restored.step(observation, 101).state == State.SEARCH
    assert restored.step(scene(), 102).state == State.APPROACH
    restored.stop("F8")
    assert restored.step(scene(), 103).state == State.IDLE


def test_startup_acquires_only_when_confidence_recovers_and_stop_resets_wait():
    agent = Agent(AgentConfig())
    agent.start()
    assert agent.step(scene([entity(confidence=0.826133)]), 10).action.kind == "release"
    acquired = agent.step(scene(), 10.5)
    assert acquired.state == State.APPROACH
    assert acquired.action.kind == "release"
    assert agent.step(scene(), 10.6).action.kind == "right"
    assert agent.step(scene([]), 10.7).state == State.SEARCH
    agent.start()
    assert agent.step(scene([]), 20).state == State.SEARCH
    assert agent.step(Observation(None, []), 20.1).state == State.IDLE


def test_missing_target_releases_and_discards_target_before_reacquiring():
    agent = Agent(AgentConfig())
    agent.start()
    agent.step(scene(), 0)
    decision = agent.step(scene([]), 0.1)
    assert decision.state == State.SEARCH
    assert decision.action.kind == "release"
    assert decision.target is None and agent.facing is None
    assert "missing" in decision.reason
    stale = Detection("monster", Rect(140, 100, 24, 28), 1.0, tracked=True)
    assert agent.step(scene([stale]), 0.2).state == State.SEARCH
    assert agent.step(scene([entity(confidence=0.89)]), 0.3).state == State.SEARCH
    acquired = agent.step(scene([entity(x=140)]), 0.4)
    assert acquired.state == State.APPROACH and acquired.action.kind == "release"
    assert agent.step(scene([entity(x=140)]), 0.5).state == State.ATTACK
    assert agent.step(scene([entity(x=140)]), 0.6).action.kind == "attack"


def test_target_association_compensates_camera_translation():
    agent = Agent(AgentConfig())
    agent.start()
    agent.step(scene([entity(x=220)]), 0)
    result = agent.step(scene([entity(x=120)], player=entity("player", 0), shift=(-100, 0)), 0.1)
    assert result.state == State.APPROACH
    assert result.target.box.x == 120
    assert result.action.kind == "right"


def test_species_survives_animation_change_and_closer_crossing_enemy():
    agent = Agent(AgentConfig())
    mushroom = replace(entity(x=220), template="catalog:Green Mushroom:stand-0")
    pig = replace(entity(x=220), template="catalog:Ribbon Pig:move-2")
    moved = replace(mushroom, box=Rect(240, 100, 24, 28),
                    template="catalog:Green Mushroom:move-1")
    agent.start()
    agent.step(scene([mushroom]), 0)
    result = agent.step(scene([pig, moved]), .3)
    assert result.target == moved
    assert result.state == State.APPROACH


def test_recorded_species_crossing_releases_and_resets_before_reacquisition():
    # Saved check frames 4341 -> 4342: mushroom vanishes and pig crosses its expected box.
    agent = Agent(AgentConfig(range_profile="classic_2h_sword"))
    mushroom = Detection("monster", Rect(452, 308, 56, 52), 1,
                         "catalog:Green Mushroom:stand-1")
    pig = Detection("monster", Rect(482, 304, 66, 49), 1, "catalog:Ribbon Pig:move-2")
    player = Detection("player", Rect(559, 299, 44, 64), 1)
    agent.start()
    agent.step(scene([mushroom], player), 0)
    agent.last_distance, agent.stalled_steps = 107, 4
    result = agent.step(scene([pig], player, shift=(32.7567, -.1355)), .3)
    assert result.state == State.SEARCH and result.action.kind == "release"
    assert result.target is None
    assert agent.last_distance is None and agent.stalled_steps == 0
    acquired = agent.step(scene([pig], player), .6)
    assert acquired.target == pig and acquired.action.kind == "release"
    assert agent.acquisitions == 2


@pytest.mark.parametrize("outcome_status", ["held", "completed"])
def test_stall_guard_counts_gap_observations_and_resets_on_progress(outcome_status):
    agent = Agent(AgentConfig())
    agent.start()
    outcome = {"status": outcome_status, "action": "right",
               "result": f"right {outcome_status}"}
    agent.step(scene([entity(x=300)]), 0)
    agent.step_input(PolicyInput(scene([entity(x=300)]), .1, outcome))
    for index in range(4):
        result = agent.step_input(PolicyInput(scene([entity(x=300)]), .2 + index, outcome))
        assert result.state == State.APPROACH
    assert agent.stalled_steps == 4
    agent.step_input(PolicyInput(scene([entity(x=290)]), 5, outcome))
    assert agent.stalled_steps == 0
    for index in range(5):
        result = agent.step_input(PolicyInput(scene([entity(x=290)]), 6 + index, outcome))
    assert result.state == State.IDLE and result.action.kind == "release"
    assert "5 observations" in result.reason


def test_attack_limit_stops_without_assuming_success():
    agent = Agent(AgentConfig(max_attack_attempts=1))
    agent.start()
    observation = scene([entity(x=140)])
    for now in (0, 0.1, 0.2):
        agent.step(observation, now)
    decision = agent.step(observation, 2)
    assert decision.state == State.IDLE
    assert "limit" in decision.reason


def test_approach_stops_when_subsequent_screenshots_show_no_progress():
    agent = Agent(AgentConfig())
    agent.start()
    for index in range(7):
        result = agent.step(scene(), index * 0.3)
    assert result.state == State.IDLE
    assert result.action.kind == "release"
    assert "No observed approach progress" in result.reason


def test_tracked_player_below_threshold_keeps_agent_running():
    agent = Agent(AgentConfig())
    agent.start()
    tracked = Detection("player", Rect(100, 100, 24, 28), 0.5, "tracked", tracked=True)
    assert agent.step(scene(player=tracked), 0).state != State.IDLE
    weak = Detection("player", Rect(100, 100, 24, 28), 0.5)
    assert agent.step(scene(player=weak), 0.1).state == State.IDLE


def attack_with(agent, mp, now):
    """Drive one in-range target to the attack decision with the given MP reading."""
    observation = scene([entity(x=130)])
    agent.start()
    agent.step_input(PolicyInput(observation, now, {"status": "not_sent"}, mp))
    agent.step_input(PolicyInput(observation, now + 0.1, {"status": "not_sent"}, mp))
    return agent.step_input(PolicyInput(observation, now + 0.2, {"status": "not_sent"}, mp))


def test_skill_attack_needs_high_mp_and_unreadable_mp_uses_basic():
    agent = Agent(AgentConfig())
    assert attack_with(agent, 80.0, 0).action.kind == "skill"
    assert attack_with(agent, None, 10).action.kind == "attack"
    assert attack_with(agent, 30.0, 20).action.kind == "attack"


@pytest.mark.parametrize("mp", [None, 0, 30, 80, 100])
def test_basic_only_mode_never_selects_skill_even_with_high_mp(mp):
    agent = Agent(AgentConfig(use_skill=False))
    agent.skill_ready = True
    assert attack_with(agent, mp, 0).action.kind == "attack"
    assert not agent.skill_ready


def test_skill_attack_has_mp_hysteresis_between_marks():
    agent = Agent(AgentConfig())
    assert [agent._attack_kind(mp) for mp in (30.0, 80.0, 30.0, 10.0, 30.0, 40.0)] == [
        "attack", "skill", "skill", "attack", "attack", "skill",
    ]


def test_mp_reading_survives_policy_input_round_trip():
    value = PolicyInput(scene(), 1.0, {"status": "not_sent"}, 55.5).to_dict()
    assert PolicyInput.from_dict(value).mp_percent == 55.5
    del value["mp_percent"]
    assert PolicyInput.from_dict(value).mp_percent is None


def hidden_track(x, feet=128, track_id="enemy:7", observed=False):
    return EnemyTrack(track_id, "catalog:Snail", "lost", (x, feet), (x, feet), None,
                      .82, (12, 8), 0.0, observed)


def tracked_entity(x=140, track_id="enemy:7"):
    return replace(entity(x=x), track_id=track_id)


def test_briefly_hidden_target_in_reach_is_attacked_in_place_from_its_track():
    agent = Agent(AgentConfig(range_profile="custom", attack_min_range=0, attack_range=65))
    agent.start()
    close = scene([tracked_entity()])
    agent.step(close, 0)
    assert agent.step(close, .1).state == State.ATTACK  # face right
    assert agent.step(close, .2).action.kind == "attack"
    # Under the player's own swing: no detection, but the tracker still holds it in reach.
    hidden = Observation(entity("player", 100), [], enemy_tracks=[hidden_track(152)])
    waiting = agent.step(hidden, .5)  # still inside the verify window
    assert waiting.action.kind == "release"
    again = agent.step(hidden, .8)
    assert again.action.kind == "attack" and "hidden target" in again.reason
    assert agent.step(hidden, 1.4).action.kind == "release"
    # More than a second since the last real match: wait for a fresh target instead.
    assert agent.step(hidden, 2.0).action.kind == "release"
    assert agent.step(hidden, 2.2).state in {State.VERIFY, State.SEARCH}
    assert all(d.action.kind != "right" or d.action.seconds <= .035 for d in [again])


@pytest.mark.parametrize("track", [hidden_track(260), hidden_track(152, feet=200),
                                   hidden_track(152, track_id="enemy:9"),
                                   hidden_track(152, observed=True)])
def test_hidden_attack_needs_the_same_track_in_reach_on_the_same_platform(track):
    agent = Agent(AgentConfig(range_profile="custom", attack_min_range=0, attack_range=65))
    agent.start()
    close = scene([tracked_entity()])
    agent.step(close, 0)
    agent.step(close, .1)
    hidden = Observation(entity("player", 100), [], enemy_tracks=[track])
    assert agent.step(hidden, .2).action.kind != "attack"


def test_hidden_target_on_the_other_side_turns_but_never_steps_toward_it():
    agent = Agent(AgentConfig(range_profile="custom", attack_min_range=0, attack_range=65))
    agent.start()
    close = scene([tracked_entity()])
    agent.step(close, 0)
    agent.step(close, .1)  # facing right
    hidden = Observation(entity("player", 100), [], enemy_tracks=[hidden_track(70)])
    turn = agent.step(hidden, .2)
    assert turn.action.kind == "left" and turn.action.seconds <= .035
    assert agent.step(hidden, .3).action.kind == "attack"


def test_policy_input_round_trip_keeps_enemy_tracks_and_track_ids():
    observation = Observation(entity("player", 100), [tracked_entity()],
                              enemy_tracks=[hidden_track(152)])
    restored = PolicyInput.from_dict(PolicyInput(observation, 1.0, {"status": "none"}).to_dict())
    assert restored.observation.monsters[0].track_id == "enemy:7"
    assert restored.observation.enemy_tracks == [hidden_track(152)]
