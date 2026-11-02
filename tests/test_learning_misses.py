import json
import time
from dataclasses import replace

from test_computed_navigation import imported
from test_runtime import app as _app

from maplebot.farming import Farming
from maplebot.navigation import RouteMap
from maplebot.navigation_executor import Feedback, Navigator
from maplebot.navigation_runtime import MISS_LIMIT, MISS_SETTLE_SECONDS

app = _app


def exploring(app, now, *, reason="Movement departed the recorded corridor"):
    """A learn_moves rotation tried the unproven floor -> ledge jump and it failed."""
    nav = app.navigation
    nav.graph = RouteMap.computed(imported())
    app.mode, app.rotating, app.learning_moves = "navigation", True, True
    app.farming = Farming({"learn_moves": True, "no_consumables": True,
                           "pet_recovery": False})
    nav.route = nav.graph.plan("floor", "ledge", max_edges=1)
    nav.agent = Navigator(nav.graph, nav.route, now)
    nav.exploring, nav.resume_combat = "m_floor_ledge", True
    nav.agent.stop(reason)
    return nav


def test_a_miss_that_lands_safely_resumes_combat_and_keeps_the_move_off(app):
    now = time.perf_counter()
    nav = exploring(app, now)
    assert nav._begin_miss(now)
    assert nav.snapshot()["learning"]["miss_pending"]
    f = Feedback(now, nav.graph.fingerprint, (100, 400), "floor", True)
    nav._settle_miss(f, now)
    assert app.mode == "navigation"  # standing still is not yet proven
    nav._settle_miss(replace(f, now=now + .35), now + .35)
    assert app.mode == "live" and app.rotation.visited.get("floor") is not None
    assert [m["landed"] for m in nav.misses] == ["floor"]
    assert "m_floor_ledge" not in nav.graph.edges
    assert app.controller.backend.events == []  # landing never sends keys
    nav.cancel("Batch over")
    fingerprint = nav.graph.fingerprint
    assert set(nav.proofs.failures("a" * 32, fingerprint)) == {"m_floor_ledge"}
    # The next batch keeps it off while the generator proposes the same geometry.
    app.position = type("P", (), {"profile": {"id": "a" * 32}})()
    app.areas.load = lambda _id: {"profile": imported()}
    nav.failed = set()  # a new session forgets in-memory failures
    nav.refresh()
    assert "m_floor_ledge" not in nav.graph.edges
    # New geometry for the move is a different move: it may be tried again.
    path = nav.proofs._path("a" * 32)
    saved = json.loads(path.read_text("utf-8"))
    saved["failed"]["m_floor_ledge"]["geometry"]["trace"][0][0] += 40
    path.write_text(json.dumps(saved), "utf-8")
    nav.refresh()
    assert "m_floor_ledge" in nav.graph.edges


def test_a_miss_without_a_steady_known_landing_stops_with_the_failure(app):
    now = time.perf_counter()
    nav = exploring(app, now)
    assert nav._begin_miss(now)
    falling = Feedback(now, nav.graph.fingerprint, (100, 380), None, True)
    nav._settle_miss(falling, now)
    assert app.mode == "navigation"
    nav._settle_miss(replace(falling, now=now + MISS_SETTLE_SECONDS),
                     now + MISS_SETTLE_SECONDS)
    assert app.stop_record.code == "NAVIGATION_FAILURE"
    assert "no safe landing" in app.stop_record.message and not nav.misses


def test_a_stale_position_while_landing_still_stops_through_the_freshness_gate(app):
    now = time.perf_counter()
    nav = exploring(app, now)
    assert nav._begin_miss(now)
    nav.feedback = Feedback(now - .6, nav.graph.fingerprint, (100, 400), "floor", True)
    nav.tick(None, now)
    assert app.stop_record.code == "PLAYER_UNCERTAIN" and not nav.misses


def test_only_a_learn_moves_explore_move_within_the_limit_may_miss(app):
    now = time.perf_counter()
    nav = exploring(app, now)
    nav.misses = [{}] * MISS_LIMIT
    assert not nav._begin_miss(now)  # one more than the limit is a failure
    nav = exploring(app, now)
    nav.exploring = None  # a proven rotation move, not an explored one
    assert not nav._begin_miss(now)
    nav = exploring(app, now)
    app.learning_moves = False
    assert not nav._begin_miss(now)


def test_a_success_clears_an_earlier_miss_and_a_miss_never_revokes_a_proof(tmp_path):
    from maplebot.move_proofs import MoveProofs

    proofs, shape = MoveProofs(tmp_path), {"from": "a", "to": "b", "kind": "jump",
                                           "trace": [[0, 0], [10, 0]]}
    proofs.record_failure("a" * 32, "m", "m_a_b", shape)
    proofs.record("a" * 32, "m", "m_b_a", {**shape, "from": "b", "to": "a"})
    assert set(proofs.failures("a" * 32, "m")) == {"m_a_b"}
    assert proofs.load("a" * 32, "m") == {"m_b_a"}
    proofs.record("a" * 32, "m", "m_a_b", shape)
    assert proofs.failures("a" * 32, "m") == {}
    proofs.record_failure("a" * 32, "m", "m_b_a", shape)
    assert proofs.load("a" * 32, "m") == {"m_a_b", "m_b_a"}


def test_a_proven_move_in_the_learning_path_misses_safely_and_loses_its_proof_at_two(app):
    # Batches 8 and 10: the proven rope grab m_fh320_rope3 dropped the player safely onto
    # fh315 and stopped the batch. Operator rule: it may miss safely; twice drops the proof.
    from maplebot.move_proofs import MoveProofs

    def proven_miss(now):
        nav = exploring(app, now)
        nav.graph = RouteMap.computed(imported(), {"m_floor_ledge"})
        nav.route = nav.graph.plan("floor", "ledge", max_edges=1)
        nav.agent = Navigator(nav.graph, nav.route, now)
        nav.exploring, nav.resume_combat = ("m_floor_ledge",), True
        nav.agent.stop("Movement departed the recorded corridor")
        assert nav._begin_miss(now)
        f = Feedback(now, nav.graph.fingerprint, (100, 400), "floor", True)
        nav._settle_miss(f, now)
        nav._settle_miss(replace(f, now=now + .35), now + .35)
        assert app.mode == "live"
        return nav

    now = time.perf_counter()
    nav = proven_miss(now)
    assert nav.misses[-1]["proof"] == "kept"
    assert "m_floor_ledge" in nav.graph.edges and "m_floor_ledge" in nav.graph.proven
    nav = proven_miss(now + 1)
    assert nav.misses[-1]["proof"] == "dropped"
    assert "m_floor_ledge" not in nav.graph.edges and "m_floor_ledge" not in nav.graph.proven

    proofs, shape = MoveProofs(app.areas.directory / "x"), {
        "from": "a", "to": "b", "kind": "jump", "trace": [[0, 0], [10, 0]]}
    proofs.record("a" * 32, "m", "m_a_b", shape)
    proofs.record_failure("a" * 32, "m", "m_a_b", shape)
    assert proofs.load("a" * 32, "m") == {"m_a_b"}
    proofs.record_failure("a" * 32, "m", "m_a_b", shape)
    assert proofs.load("a" * 32, "m") == set()
    assert proofs.failure_counts("a" * 32, "m") == {"m_a_b": 2}
