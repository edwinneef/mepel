from maplebot.combat_evidence import CombatEvidence


def test_stopped_evidence_retains_frame_and_distinguishes_input_from_effect():
    log = CombatEvidence("session")
    assert log.snapshot() is None
    log.start("probe:attack")
    observation = {"frame_id": "session:3", "same_platform_targets": [{"distance_px": 150}]}
    log.observe(observation)
    log.record("input_outcome", "attack completed", ticket=1)
    observation["same_platform_targets"].clear()
    log.stop("F8 pressed")
    log.stop("Settings opened")
    log.record("observed_effect", "Operator confirmed attack")
    saved = log.snapshot()
    assert saved["stop_reason"] == "F8 pressed"
    assert saved["hit_confirmed"] is None
    assert saved["events"][1]["observation"]["same_platform_targets"] == [{"distance_px": 150}]
    saved["events"].clear()
    assert len(log.snapshot()["events"]) == 4


def test_evidence_is_bounded_and_new_run_does_not_inherit_old_outcomes():
    log = CombatEvidence("session")
    log.start("combat")
    for i in range(100):
        log.record("decision", str(i))
    assert len(log.snapshot()["events"]) == 64
    log.stop("Stopped")
    log.start("preview")
    assert log.snapshot()["run"] == 2
    assert log.snapshot()["stop_reason"] is None
    assert len(log.snapshot()["events"]) == 1
    log.record("input_outcome", "old attack canceled", submitted_at=0)
    assert len(log.snapshot()["events"]) == 1
