"""One prepared supervised learn_moves farming session. Invoke --run only after operator go.

Started from the local start window (tools/floor_batch_button.py --farm ...). Farming goes
through the engine's normal arm command and every gate; when a platform is clear, rotation
tries one unproven computed move at a time and saves each completed move as a proof. The
batch is bounded by --minutes, stops at its first failure and never retries.
"""
import argparse
import json
import time
from pathlib import Path

from tools.farming_check import run
from tools.navigation_check import Debugger
from tools.prepared_floor_check import restore_focus
from tools.prepared_route_check import route_blocker, settle


def proven(status: dict) -> int:
    edges = ((status.get("navigation") or {}).get("map") or {}).get("edges") or []
    return sum(1 for edge in edges if edge.get("proven"))


def main(argv: list[str] | None = None, *, api=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--focus", action="store_true")
    parser.add_argument("--area", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--minutes", type=int, choices=range(1, 31), default=5)
    args = parser.parse_args(argv)
    started = time.monotonic()
    api = api or Debugger()
    output = (Path(__file__).resolve().parents[1] / "artifacts" / "farming-checks"
              / f"prepared-farm-{args.origin}-{time.time_ns()}")
    try:
        status = restore_focus(api) if args.focus else api.status()
        status, steady = settle(api, status, args.area, args.origin)
    except RuntimeError as error:
        print(json.dumps({"blocked": str(error), "input_sent": False}), flush=True)
        return 1
    problem = route_blocker(status, args.area, args.origin, args.origin) or (
        None if steady else f"Recognition did not hold steady on {args.origin} for 1.5 s")
    if problem:
        print(json.dumps({"blocked": problem, "input_sent": False}), flush=True)
        return 1
    before = proven(status)
    print(f"Starting one {args.minutes}-minute learn_moves farm from {args.origin}", flush=True)
    try:
        result = run(api, output, area=args.area, session_minutes=args.minutes,
                     learn_moves=True)
    except Exception as error:
        print(json.dumps({"error": str(error), "result": str(output)}), flush=True)
        result = {"outcome": "failure", "error": str(error)}
    after = result.get("after") or api.status()
    print(json.dumps({"result": str(output / "result.json"), "outcome": result.get("outcome"),
                      "error": result.get("error"), "stop_error": result.get("stop_error"),
                      "proven_before": before, "proven_after": proven(after),
                      "input_state": after.get("input_state"), "stop": after.get("stop"),
                      "command_seconds": round(time.monotonic() - started, 2)}), flush=True)
    if result.get("outcome") != "functional_success":
        print("Control returned to operator. Move to safety; no retry.", flush=True)
        if not (after.get("alarm") or {}).get("active"):
            import winsound
            winsound.PlaySound(str(Path(__file__).resolve().parents[1]
                                   / "src/maplebot/static/alarm.wav"), winsound.SND_FILENAME)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
