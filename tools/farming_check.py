"""Bounded no-consumables farming check; normal engine commands retain all input gates."""
import argparse
import json
import time
from pathlib import Path

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


def run(api, output: Path, *, area: str, single_platform=False, session_minutes=15,
        clock=time.monotonic, sleep=time.sleep):
    if type(session_minutes) is not int or not 1 <= session_minutes <= 120:
        raise ValueError("session_minutes must be an integer between 1 and 120")
    before = api.status()
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
    result = {"before": before, "samples": [], "error": None, "stop_error": None,
              "outcome": "failure"}
    previous_run = (before.get("combat_evidence") or {}).get("run", 0)
    run_id = None
    started = clock()
    try:
        settings = {"session_minutes": session_minutes, "pet_recovery": False,
                    "no_consumables": True}
        if single_platform:
            settings["single_platform"] = True
        api.command("arm", {"farming": settings})
        while clock() - started < session_minutes * 60 + 10:
            sample = api.status()
            result["samples"].append({key: sample.get(key) for key in (
                "mode", "farming", "position", "stop", "alarm", "last_action", "combat_evidence")})
            if sample.get("session_id") != before.get("session_id"):
                raise RuntimeError("Engine session changed during farming")
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
                if (stop.get("code") == "FARMING_STOP"
                        and message == "Farming session limit reached; restart manually"):
                    if clock() - started < session_minutes * 60 or not progress["repeated_combat"]:
                        raise RuntimeError("Session ended without bounded repeated-combat evidence")
                    result["outcome"] = "functional_success"
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
        except Exception as error:
            result["after_error"] = str(error)
        if result["stop_error"] or result.get("after_error"):
            result["outcome"] = "failure"
        result["combat_progress"] = combat_progress(result["samples"])
        result["seconds"] = clock() - started
        output.mkdir(parents=True, exist_ok=False)
        (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--area", required=True, help="Verified taught area ID")
    parser.add_argument("--single-platform", action="store_true",
                        help="Clear continuous floor only; no route rotation")
    parser.add_argument("--session-minutes", type=int, default=15)
    parser.add_argument("--bot-friendly-server", action="store_true", required=True)
    args = parser.parse_args()
    output = Path("artifacts/farming-checks") / time.strftime("%Y%m%d-%H%M%S")
    result = run(Debugger(), output, area=args.area, single_platform=args.single_platform,
                 session_minutes=args.session_minutes)
    print(json.dumps({"result": str(output / "result.json"), "error": result["error"],
                      "stop_error": result["stop_error"], "outcome": result["outcome"]}))
    if result["outcome"] != "functional_success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

