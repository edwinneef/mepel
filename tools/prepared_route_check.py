"""One prepared supervised route between two platforms. Invoke --run only after operator go.

Started from the local start window (tools/floor_batch_button.py --route ...). The route
goes through the engine's normal nav_go command and every existing gate; a completed move
is saved as a proof. The batch is one route, stops at its first failure and never retries.
"""
import argparse
import json
import time
from pathlib import Path

from tools.navigation_check import Debugger, run
from tools.prepared_floor_check import restore_focus


def route_blocker(status: dict, area: str, origin: str, target: str) -> str | None:
    """Why this route may not start now; None when every preflight passes."""
    if status.get("capture_only"):
        return "Capture-only session: restart with .\\restart.ps1 -EnableGameplayInput"
    if status.get("mode") != "capture":
        return "Bot must be Off"
    state = status.get("input_state") or {}
    if state.get("held_keys") != [] or state.get("active") or state.get("queued"):
        return "Input must be released and idle"
    position = status.get("position") or {}
    if position.get("area_id") != area:
        return "Track the route's map first"
    if (position.get("surface_id") != origin or position.get("stale")
            or position.get("held") or position.get("provisional")):
        return f"Stand still on the recognized start platform {origin}"
    nav = (status.get("navigation") or {}).get("map") or {}
    nodes = {node["id"]: node for node in nav.get("nodes") or []}
    if nav.get("area_id") != area or target not in nodes or nodes[target]["excluded"]:
        return f"Navigation routes for {target} are not loaded"
    if not status.get("focused"):
        return "Focus MapleStory before go"
    # nav_go needs the marker and the name tag to agree on consecutive frames.
    feedback = (status.get("navigation") or {}).get("feedback") or {}
    if not feedback.get("motion_ok") or feedback.get("surface") != origin:
        return f"Waiting for the minimap marker and name tag to agree on {origin}"
    return None


def settle(api, status: dict, area: str, origin: str, *, seconds: float = 8,
           steady: float = 1.5, clock=time.monotonic, sleep=time.sleep) -> tuple[dict, bool]:
    """Latest status, and whether every preflight held for `steady` seconds; reads only.

    Right after focus returns, recognition and the marker/name-tag agreement come back
    within a few frames but drop out now and then for about a second; the move waits
    until they hold.
    """
    deadline, since = clock() + seconds, None
    while True:
        now = clock()
        if route_blocker(status, area, origin, origin):
            since = None
        elif since is None:
            since = now
        if since is not None and now - since >= steady:
            return status, True
        if now >= deadline:
            return status, False
        sleep(.1)
        status = api.status()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--focus", action="store_true")
    parser.add_argument("--area", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    api = Debugger()
    output = (Path(__file__).resolve().parents[1] / "artifacts" / "navigation-checks"
              / f"prepared-route-{args.origin}-{args.target}-{time.time_ns()}")
    try:
        status = restore_focus(api) if args.focus else api.status()
        status, steady = settle(api, status, args.area, args.origin)
    except RuntimeError as error:
        print(json.dumps({"blocked": str(error), "input_sent": False}), flush=True)
        return 1
    problem = route_blocker(status, args.area, args.origin, args.target) or (
        None if steady else f"Recognition did not hold steady on {args.origin} for 1.5 s")
    if problem:
        print(json.dumps({"blocked": problem, "input_sent": False}), flush=True)
        return 1
    print(f"Starting one route {args.origin} -> {args.target}", flush=True)
    try:
        result = run(api, output, limit=1, chosen=[args.target])
    except Exception as error:
        print(json.dumps({"error": str(error), "result": str(output)}), flush=True)
        result = {"failure": str(error)}
    after = api.status()
    print(json.dumps({"result": str(output / "result.json"), "arrived": result.get("arrived"),
                      "failure": result.get("failure"), "proven_after": result.get("proven_after"),
                      "input_state": after.get("input_state"), "stop": after.get("stop"),
                      "command_seconds": round(time.monotonic() - started, 2)}), flush=True)
    if result.get("failure"):
        print("Control returned to operator. Move to safety; no retry.", flush=True)
        if not (after.get("alarm") or {}).get("active"):
            import winsound
            winsound.PlaySound(str(Path(__file__).resolve().parents[1]
                                   / "src/maplebot/static/alarm.wav"), winsound.SND_FILENAME)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
