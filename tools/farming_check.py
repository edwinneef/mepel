"""Bounded no-consumables farming check; normal engine commands retain all input gates."""
import argparse
import json
import time
from pathlib import Path

from tools.navigation_check import Debugger, readiness


def run(api, output: Path, *, area: str, clock=time.monotonic, sleep=time.sleep):
    before = api.status()
    problem = readiness(before)
    if problem:
        raise RuntimeError(problem)
    if (before.get("position") or {}).get("area_id") != area:
        raise RuntimeError("Wrong map; no farming started")
    player = before.get("player") or {}
    if player.get("tracked") or player.get("confidence", 0) < .9:
        raise RuntimeError("Player not freshly recognized; no farming started")
    result = {"before": before, "samples": [], "error": None, "stop_error": None}
    started = clock()
    try:
        api.command("arm", {"farming": {"session_minutes": 15, "pet_recovery": False,
                                        "no_consumables": True}})
        while clock() - started < 910:
            sample = api.status()
            result["samples"].append({key: sample.get(key) for key in (
                "mode", "farming", "position", "stop", "alarm", "last_action")})
            if sample.get("session_id") != before.get("session_id"):
                raise RuntimeError("Engine session changed during farming")
            if sample.get("mode") not in {"pending_arm", "live", "navigation"}:
                break
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
        except Exception as error:
            result["after_error"] = str(error)
        result["seconds"] = clock() - started
        output.mkdir(parents=True, exist_ok=False)
        (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--area", required=True, help="Verified taught area ID")
    parser.add_argument("--bot-friendly-server", action="store_true", required=True)
    args = parser.parse_args()
    output = Path("artifacts/farming-checks") / time.strftime("%Y%m%d-%H%M%S")
    result = run(Debugger(), output, area=args.area)
    print(json.dumps({"result": str(output / "result.json"), "error": result["error"],
                      "stop_error": result["stop_error"]}))
    if result["error"] or result["stop_error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

