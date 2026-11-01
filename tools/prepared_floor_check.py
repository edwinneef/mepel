"""One prepared floor-only minute. Invoke --run only after explicit operator go."""
import argparse
import json
import time
from pathlib import Path

from tools.farming_check import run
from tools.navigation_check import Debugger

AREA = "e67f1ca1ef2d4ee2a4383dc66a761242"


def floor_blocker(status):
    if status.get("mode") != "capture":
        return "Bot must be Off"
    if (status.get("alarm") or {}).get("active"):
        return "Acknowledge alarm in overlay first"
    state = status.get("input_state") or {}
    if state.get("held_keys") != [] or state.get("active") or state.get("queued"):
        return "Input must be released and idle"
    position = status.get("position") or {}
    if (position.get("area_id") != AREA or position.get("surface_id") != "fh66"
            or position.get("stale") or position.get("held")):
        return "Stand on recognized floor fh66 in Snail Hunting Ground III"
    if not status.get("focused"):
        return "Focus MapleStory before go"
    if not (status.get("readiness") or {}).get("combat", {}).get("ready"):
        return "Combat readiness blocked"
    return None


def restore_focus(api):
    status = api.status()
    if status.get("mode") != "capture":
        raise RuntimeError("Bot must be Off before restoring focus")
    state = status.get("input_state") or {}
    if state.get("held_keys") != [] or state.get("active") or state.get("queued"):
        raise RuntimeError("Input must be released and idle")
    # Cached capture status can still say focused just after the operator clicks the GUI.
    if not api.command("focus_game", {"click_fallback": True}).get("focused"):
        raise RuntimeError("Guarded focus failed; no retry")
    return api.status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--focus", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    api = Debugger()
    output = Path("artifacts/farming-checks") / ("prepared-floor-" + str(time.time_ns()))
    # Imports and output selection precede the final fresh check. Never wait for mobs.
    status = restore_focus(api) if args.focus else api.status()
    if problem := floor_blocker(status):
        print(json.dumps({"blocked": problem, "input_sent": False}), flush=True)
        return 1
    print("Starting prepared floor-only minute", flush=True)
    try:
        result = run(api, output, area=AREA, single_platform=True,
                     session_minutes=1, consumables=True, require_enemy=True)
    except Exception as error:
        print(json.dumps({"error": str(error), "result": str(output)}), flush=True)
        return 1
    after = result.get("after") or {}
    print(json.dumps({"result": str(output / "result.json"),
                      "outcome": result["outcome"], "error": result["error"],
                      "stop_error": result.get("stop_error"),
                      "input_state": after.get("input_state"), "stop": after.get("stop"),
                      "command_seconds": time.monotonic() - started}), flush=True)
    if result["outcome"] != "functional_success":
        print("Control returned to operator. Move to safety; no retry.", flush=True)
        if not (after.get("alarm") or {}).get("active"):
            import winsound
            winsound.PlaySound(str(Path(__file__).resolve().parents[1]
                                   / "src/maplebot/static/alarm.wav"), winsound.SND_FILENAME)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
