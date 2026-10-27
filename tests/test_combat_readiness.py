from dataclasses import replace

import pytest

from maplebot.combat_readiness import summarize
from maplebot.config import AgentConfig, Config


def entity(x, y=100, confidence=1.0, tracked=False):
    return {"box": {"x": x, "y": y, "width": 20, "height": 30},
            "confidence": confidence, "tracked": tracked}


def snapshot():
    return {
        "frame": {"id": "current", "available": True, "captured_at": 10},
        "player": entity(100), "monsters": [entity(250)],
        "required_probes": ["attack", "skill", "left"],
        "probes": {"left": {"confirmed": True}},
        "bindings": {"attack": "space", "skill": "ctrl"},
    }


def test_only_fresh_confident_same_platform_targets_supply_distance():
    status = snapshot()
    status["monsters"] += [entity(101, y=200), entity(102, confidence=0.89),
                           entity(103, tracked=True), entity(40)]
    result = summarize(status, Config(), 10.1)
    assert [target["distance_px"] for target in result["same_platform_targets"]] == [60, 150]
    assert result["same_platform_targets"][0]["direction"] == "left"
    assert result["unconfirmed_controls"] == ["attack", "skill"]
    assert result["bindings"] == {"attack": "space", "skill": "ctrl"}
    assert result["hit_confirmed"] is None


@pytest.mark.parametrize("change", ["old", "future", "tracked", "missing", "weak"])
def test_unusable_player_never_produces_range_evidence(change):
    status = snapshot()
    if change in {"old", "future"}:
        status["frame"]["captured_at"] = 8 if change == "old" else 12
    elif change == "tracked":
        status["player"]["tracked"] = True
    elif change == "weak":
        status["player"]["confidence"] = 0.89
    else:
        status["player"] = None
    result = summarize(status, Config(), 10.1)
    assert not result["fresh_player"]
    assert result["same_platform_targets"] == []


def test_live_detections_override_old_decision_detections():
    status = snapshot()
    status["live_detections"] = {**snapshot(), "player": None}
    assert summarize(status, Config(), 10.1)["same_platform_targets"] == []


def test_distance_bands_match_policy_boundaries_without_claiming_hits():
    config = replace(Config(), agent=AgentConfig(attack_min_range=80, attack_range=200))
    status = snapshot()
    status["monsters"] = [entity(x) for x in (179, 180, 300, 301)]
    status["probes"] = {key: {"confirmed": True} for key in status["required_probes"]}
    result = summarize(status, config, 10.1)
    assert [target["configured_band"] for target in result["same_platform_targets"]] == [
        "too_close", "in_range", "in_range", "approach",
    ]
    assert result["unconfirmed_controls"] == []
    assert result["hit_confirmed"] is None
