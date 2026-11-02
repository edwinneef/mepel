"""Bounded farming check; normal engine commands retain all input gates.

Without consumables, low HP/MP stops the run. With them, verified potion keys sustain it.
"""
import argparse
import json
import math
import time
from pathlib import Path

from maplebot.farming import CHECKPOINT_STOP, Farming
from maplebot.farming_routes import identifier
from tools.navigation_check import Debugger, readiness


def combat_progress(samples: list[dict]) -> dict:
    """Match dispatch outcomes to acquisitions, never infer hits or kills."""
    attacks, completed = {}, set()
    for sample in samples:
        evidence = sample.get("combat_evidence") or {}
        for event in evidence.get("events", []):
            ticket = event.get("ticket")
            if type(ticket) is not int:
                continue
            if (event.get("kind") == "decision" and event.get("action") in {"attack", "skill"}
                    and type(event.get("acquisition")) is int and event["acquisition"] > 0):
                attacks[ticket] = event["acquisition"]
            if (event.get("kind") == "input_outcome"
                    and event.get("result") in {"attack completed", "skill completed"}):
                completed.add(ticket)
    acquisitions = {attacks[ticket] for ticket in completed if ticket in attacks}
    return {"attacked_acquisitions": len(acquisitions),
            "completed_attacks": len(completed.intersection(attacks)),
            "repeated_combat": len(acquisitions) >= 2,
            "hits_confirmed": None, "kills_confirmed": None}


ON_ROPE = "You're on a rope; stand on a platform"


def rotation_blocker(status: dict, *, learn_moves: bool = False) -> str | None:
    """Reject impossible rotation connectivity; engine planning still owns route safety.

    Operator rule (2026-11-02): rotation routes over computed moves without a prior proof,
    so every usable edge counts. `learn_moves` is accepted for existing callers and
    changes nothing.
    """
    position = status.get("position") or {}
    if position.get("kind") == "rope":
        return ON_ROPE
    if position.get("stale") or position.get("held") or not position.get("feet"):
        return "Wait for a fresh mapped position before rotation"
    graph = (status.get("navigation") or {}).get("map") or {}
    origin = position.get("surface_id")
    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    if origin not in nodes or nodes[origin].get("excluded"):
        return "Rotation origin is outside the usable map"
    targets = {key for key, node in nodes.items() if key != origin
               and node.get("kind") == "platform"
               and not node.get("excluded") and not node.get("unproven")}
    reached, frontier = {origin}, {origin}
    for _ in range(8):
        frontier = {edge["to"] for edge in graph.get("edges", [])
                    if edge["from"] in frontier} - reached
        if frontier & targets:
            return None
        reached |= frontier
    return "No rotation route from this platform; move to a connected combat platform"

def fresh_position(api, status: dict, *, seconds: float = 2, clock=time.monotonic,
                   sleep=time.sleep) -> dict:
    """Re-read status through a brief recognition gap. Reads only; sends no input."""
    deadline = clock() + seconds
    while True:
        position = status.get("position") or {}
        if not (position.get("stale") or position.get("held") or not position.get("feet")):
            return status
        if clock() >= deadline:
            return status
        sleep(.1)
        status = api.status()


def circuit_progress(samples: list[dict], stops: list[str]) -> dict:
    """Observed movement and subsequent dispatches; never native hit evidence."""
    visited, completed = set(), set()
    navigation = resumed = False
    for sample in samples:
        position = sample.get("position") or {}
        surface = position.get("surface_id")
        fresh = not any(position.get(key) for key in ("stale", "held", "provisional"))
        if surface in stops and fresh:
            visited.add(surface)
        if sample.get("mode") == "navigation":
            navigation = True
        progress = combat_progress([sample])["completed_attacks"]
        tickets = {event["ticket"] for event in (sample.get("combat_evidence") or {}).get(
            "events", []) if event.get("kind") == "input_outcome"
            and event.get("result") in {"attack completed", "skill completed"}
            and type(event.get("ticket")) is int}
        if (navigation and len(visited) >= 2 and surface in stops
                and fresh and sample.get("mode") == "live" and progress and tickets - completed):
            resumed = True
        completed.update(tickets)
    return {"visited_stops": sorted(visited), "navigation_observed": navigation,
            "combat_after_arrival": resumed}


def checked_circuit(api, area: str, circuit: dict) -> dict:
    """Resolve a saved revision and validate it without granting input authority."""
    route_id = identifier(circuit.get("id"))
    revision = circuit.get("revision")
    if type(revision) is not int or revision < 1:
        raise ValueError("Select a saved circuit revision")
    routes = api.command("farm_route_list", {"area_id": area}).get("routes", [])
    route = next((route for route in routes if route["id"] == route_id), None)
    if route is None or route["area_id"] != area:
        raise ValueError("Circuit is not saved for this map")
    if route["revision"] != revision:
        raise ValueError("Circuit changed; reload and select it again")
    if not route["loop"]:
        raise ValueError("Timed farming needs a looping circuit")
    checked = api.command("farm_route_validate", {"route": route})
    if not checked.get("valid"):
        raise ValueError("; ".join(checked.get("errors", [])) or "Circuit is not valid")
    return route


def run(api, output: Path, *, area: str, single_platform=False, session_minutes=15,
        checkpoint_seconds=None, consumables=False, require_enemy=False, learn_moves=False,
        circuit=None, clock=time.monotonic, sleep=time.sleep):
    if type(session_minutes) is not int or not 1 <= session_minutes <= 120:
        raise ValueError("session_minutes must be an integer between 1 and 120")
    if checkpoint_seconds is not None and (
            type(checkpoint_seconds) is not int or not 1 <= checkpoint_seconds <= 10):
        raise ValueError("checkpoint_seconds must be an integer between 1 and 10")
    if consumables and checkpoint_seconds is not None:
        raise ValueError("Checkpoints run without consumables")
    if learn_moves and single_platform:
        raise ValueError("learn_moves needs platform rotation, not single_platform")
    if circuit is not None and (single_platform or learn_moves):
        raise ValueError("A saved circuit cannot be combined with single-platform or exploration")
    # Reserve evidence storage before reading readiness or sending any commands.
    output.mkdir(parents=True, exist_ok=False)
    before = api.status()
    if not single_platform:
        before = fresh_position(api, before)
    if checkpoint_seconds is not None:
        if not before.get("farming_checkpoint_available"):
            raise RuntimeError("Installed engine lacks bounded farming checkpoint support")
        if not (before.get("frame") or {}).get("source_id") or not before.get("code_revision"):
            raise RuntimeError("Checkpoint needs engine source/session identity")
    if single_platform:
        problem = ("Capture-only session" if before.get("capture_only") else
                   "Bot must be Off" if before.get("mode") != "capture" else
                   "Focus MapleStory" if not before.get("focused") else
                   None if (before.get("readiness") or {}).get("combat", {}).get("ready") else
                   "Combat readiness is not confirmed")
    else:
        problem = readiness(before)
    if problem:
        raise RuntimeError(problem)
    if (before.get("position") or {}).get("area_id") != area:
        raise RuntimeError("Wrong map; no farming started")
    player = before.get("player") or {}
    if player.get("tracked") or player.get("confidence", 0) < .9:
        raise RuntimeError("Player not freshly recognized; no farming started")
    if not single_platform and (problem := rotation_blocker(before, learn_moves=learn_moves)):
        raise RuntimeError("No farming started: " + problem)
    route = None
    if circuit is not None:
        route = checked_circuit(api, area, circuit)
        circuit = {"id": route["id"], "revision": route["revision"]}
        # Route reads can take time; reacquire all preflight evidence before arm.
        before = fresh_position(api, api.status())
        if problem := readiness(before):
            raise RuntimeError(problem)
        if (before.get("position") or {}).get("area_id") != area:
            raise RuntimeError("Wrong map; no farming started")
        if problem := rotation_blocker(before):
            raise RuntimeError(problem)
        if (before.get("position") or {}).get("surface_id") not in route["stops"]:
            raise RuntimeError("Stand on a selected circuit stop before starting")
        player = before.get("player") or {}
        if player.get("tracked") or player.get("confidence", 0) < .9:
            raise RuntimeError("Player not freshly recognized; no farming started")
    if require_enemy:
        box = player.get("box") or {}
        feet = box.get("y", 0) + box.get("height", 0)
        if not box or not any(
                not monster.get("tracked") and monster.get("confidence", 0) >= .9
                and abs(monster["box"]["y"] + monster["box"]["height"] - feet) <= 18
                for monster in before.get("monsters", [])):
            raise RuntimeError("No fresh same-platform enemy; no farming started")
    settings = {"session_minutes": session_minutes, "pet_recovery": False,
                "no_consumables": not consumables}
    # Recovery follows the operator's potion thresholds (operator decision, 2026-11-02), so
    # the engine's rule that potions fire at or before recovery always holds.
    potion = (before.get("autopotter") or {}).get("settings") or {}
    for name in ("hp_threshold", "mp_threshold"):
        value = potion.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            settings[name] = min(95, max(1, value))
    if single_platform:
        settings["single_platform"] = True
    if learn_moves:
        settings["learn_moves"] = True
    if checkpoint_seconds is not None:
        settings["checkpoint_seconds"] = checkpoint_seconds
    # Apply the same health policy before taking control, while safe staging is possible.
    health = Farming(settings)
    health.start(0)
    if problem := health.check(0, (before.get("autopotter") or {}).get("readings", {}), True):
        raise RuntimeError("No farming started: " + problem)
    result = {"before": before, "samples": [], "error": None, "stop_error": None,
              "outcome": "failure", "checkpoint_seconds": checkpoint_seconds,
              "full_session_passed": False, "circuit": circuit, "settings": settings}
    previous_run = (before.get("combat_evidence") or {}).get("run", 0)
    run_id = None
    started = clock()
    try:
        payload = {"farming": settings}
        if circuit is not None:
            payload["circuit"] = circuit
        api.command("arm", payload)
        deadline = checkpoint_seconds + 5 if checkpoint_seconds else session_minutes * 60 + 10
        while clock() - started < deadline:
            sample = api.status()
            result["samples"].append({key: sample.get(key) for key in (
                "mode", "farming", "position", "stop", "alarm", "last_action", "combat_evidence",
                "captured_at", "capture_clock", "focused", "window", "stage_timing",
                "input_refusal", "input_state", "frame", "code_revision", "autopotter")})
            if sample.get("session_id") != before.get("session_id"):
                raise RuntimeError("Engine session changed during farming")
            if checkpoint_seconds is not None and (
                    (sample.get("frame") or {}).get("source_id") != before["frame"]["source_id"]
                    or sample.get("code_revision") != before["code_revision"]):
                raise RuntimeError("Engine source changed during checkpoint")
            evidence = sample.get("combat_evidence") or {}
            if (evidence.get("session_id") != before.get("session_id")
                    or evidence.get("activity") != "combat"
                    or evidence.get("run", 0) <= previous_run):
                raise RuntimeError("Current combat evidence unavailable")
            if run_id is not None and evidence["run"] != run_id:
                raise RuntimeError("Combat run changed during farming")
            run_id = evidence["run"]
            if sample.get("mode") not in {"pending_arm", "live", "navigation"}:
                stop = sample.get("stop") or {}
                message = stop.get("message", "")
                progress = combat_progress(result["samples"])
                if checkpoint_seconds is not None and stop.get("message") == CHECKPOINT_STOP:
                    if (stop.get("code") != "FARMING_STOP"
                            or clock() - started < checkpoint_seconds
                            or not progress["completed_attacks"]):
                        raise RuntimeError(
                            "Checkpoint ended without bounded completed-attack evidence")
                    result["outcome"] = "checkpoint_success"
                elif (stop.get("code") == "FARMING_STOP"
                        and message == "Farming session limit reached; restart manually"):
                    if checkpoint_seconds is not None:
                        raise RuntimeError("Checkpoint exceeded its engine limit")
                    if clock() - started < session_minutes * 60 or not progress["repeated_combat"]:
                        raise RuntimeError("Session ended without bounded repeated-combat evidence")
                    result["outcome"] = "functional_success"
                    result["full_session_passed"] = True
                elif stop.get("code") == "FARMING_DONE":
                    result["outcome"] = "nothing_left"
                elif (stop.get("code") == "OPERATOR_STOP" or
                      stop.get("code") == "FARMING_STOP" and message in {
                    "HP low; no consumables available, stopped",
                    "MP low; no consumables available, stopped",
                }):
                    result["outcome"] = "safe_stop"
                else:
                    raise RuntimeError(message or "Farming exited without a stop reason")
                break
            if single_platform and sample.get("mode") == "navigation":
                raise RuntimeError("Single-platform combat entered navigation")
            if not sample.get("focused"):
                raise RuntimeError("Game lost focus")
            if (sample.get("position") or {}).get("area_id") != area:
                raise RuntimeError("Map changed during farming")
            sleep(.33)
        else:
            raise RuntimeError("Farming exceeded bounded session deadline")
    except Exception as error:
        result["error"] = str(error)
    finally:
        try:
            api.command("stop")
        except Exception as error:
            result["stop_error"] = str(error)
        try:
            result["after"] = api.status()
            if result["after"].get("mode") != "capture":
                result["stop_error"] = "Engine did not confirm Off after Stop"
            state = result["after"].get("input_state")
            if state is not None or checkpoint_seconds is not None or circuit is not None:
                if (not isinstance(state, dict) or state.get("enabled") is not False
                        or state.get("held_keys") != []):
                    result["stop_error"] = "Engine did not confirm disabled input and released keys"
        except Exception as error:
            result["after_error"] = str(error)
        if result["stop_error"] or result.get("after_error"):
            result["outcome"] = "failure"
            result["full_session_passed"] = False
        result["combat_progress"] = combat_progress(result["samples"])
        if route is not None:
            result["circuit_progress"] = circuit_progress(result["samples"], route["stops"])
            if (result["outcome"] == "functional_success"
                    and not result["circuit_progress"]["combat_after_arrival"]):
                result["outcome"] = "failure"
                result["full_session_passed"] = False
                result["error"] = "Circuit did not demonstrate navigation and renewed combat"
        # Moves a learn_moves batch missed but landed safely from; it kept farming.
        result["learning"] = ((result.get("after") or {}).get("navigation") or {}).get("learning")
        result["seconds"] = clock() - started
        (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if result["outcome"] == "failure":
            # Diagnostics run only after Stop/release, never while the character is exposed.
            from tools.failure_report import run as report_failure
            try:
                report_failure(output / "result.json", output / "failure")
            except (ValueError, OSError, KeyError, TypeError) as error:
                (output / "report-error.txt").write_text(str(error), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--area", required=True, help="Verified taught area ID")
    parser.add_argument("--single-platform", action="store_true",
                        help="Clear continuous floor only; no route rotation")
    parser.add_argument("--require-enemy", action="store_true",
                        help="Require a fresh same-platform enemy immediately before starting")
    parser.add_argument("--learn-moves", action="store_true",
                        help="Supervised: rotation may try one unproven move at a time")
    parser.add_argument("--session-minutes", type=int, default=15)
    parser.add_argument("--consumables", action="store_true",
                        help="Sustain HP/MP with the verified potion keys instead of stopping")
    parser.add_argument("--checkpoint-seconds", type=int, choices=range(1, 11),
                        help="Bounded diagnostic only; never counts as a full farming pass")
    parser.add_argument("--bot-friendly-server", action="store_true", required=True)
    args = parser.parse_args()
    output = Path("artifacts/farming-checks") / time.strftime("%Y%m%d-%H%M%S")
    result = run(Debugger(), output, area=args.area, single_platform=args.single_platform,
                 session_minutes=args.session_minutes, checkpoint_seconds=args.checkpoint_seconds,
                 consumables=args.consumables, require_enemy=args.require_enemy,
                 learn_moves=args.learn_moves)
    print(json.dumps({"result": str(output / "result.json"), "error": result["error"],
                      "stop_error": result["stop_error"], "outcome": result["outcome"]}))
    if result["outcome"] not in {"functional_success", "checkpoint_success"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

