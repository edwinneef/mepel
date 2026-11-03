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

from tools.farming_check import ON_ROPE, run
from tools.navigation_check import Debugger
from tools.prepared_floor_check import restore_focus
from tools.prepared_route_check import route_blocker, settle


def standing_platform(
    api, status: dict, area: str, *, seconds: float = 3, clock=time.monotonic, sleep=time.sleep
) -> str | None:
    """The usable platform the player stands on, read fresh; None if none appears in time.

    Reads only. The caller still waits for every preflight to hold steady on it.
    """
    deadline = clock() + seconds
    while True:
        position = status.get("position") or {}
        nav = (status.get("navigation") or {}).get("map") or {}
        usable = {
            node["id"]
            for node in nav.get("nodes") or []
            if node.get("kind") == "platform" and not node.get("excluded")
        }
        surface = position.get("surface_id")
        if (
            position.get("area_id") == area
            and nav.get("area_id") == area
            and surface in usable
            and not position.get("stale")
            and not position.get("held")
            and not position.get("provisional")
        ):
            return surface
        if clock() >= deadline:
            return None
        sleep(0.1)
        status = api.status()


def proven(status: dict) -> int:
    edges = ((status.get("navigation") or {}).get("map") or {}).get("edges") or []
    return sum(1 for edge in edges if edge.get("proven"))


def main(argv: list[str] | None = None, *, api=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--focus", action="store_true")
    parser.add_argument("--area", required=True)
    parser.add_argument("--origin", help="Start platform; default: where the player stands")
    parser.add_argument("--minutes", type=int, choices=range(1, 31), default=5)
    parser.add_argument(
        "--single",
        action="store_true",
        help="Farm only the start platform, sustained by the verified potion keys",
    )
    parser.add_argument("--circuit", help="Saved looping circuit ID")
    parser.add_argument("--revision", type=int, help="Expected saved circuit revision")
    parser.add_argument(
        "--consumables", action="store_true", help="Use verified HP/MP potion keys during rotation"
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:8765")
    parser.add_argument("--expected-session")
    parser.add_argument("--batch-token", type=json.loads)
    args = parser.parse_args(argv)
    if bool(args.circuit) != (args.revision is not None) or args.single and args.circuit:
        parser.error("Provide --circuit and --revision together, without --single")
    started = time.monotonic()
    owns_api = api is None
    api = api or (
        Debugger(
            args.endpoint, expected_session=args.expected_session, batch_token=args.batch_token
        )
        if args.expected_session or args.batch_token or args.endpoint != "http://127.0.0.1:8765"
        else Debugger()
    )
    try:
        try:
            status = restore_focus(api) if args.focus else api.status()
            args.origin = args.origin or standing_platform(api, status, args.area)
            if args.origin is None:
                on_rope = (api.status().get("position") or {}).get("kind") == "rope"
                raise RuntimeError(
                    ON_ROPE if on_rope else "Stand still on a recognized platform of this map first"
                )
            status, steady = settle(api, status, args.area, args.origin)
        except RuntimeError as error:
            print(json.dumps({"blocked": str(error), "input_sent": False}), flush=True)
            return 1
        problem = route_blocker(status, args.area, args.origin, args.origin) or (
            None if steady else f"Recognition did not hold steady on {args.origin} for 1.5 s"
        )
        if problem:
            print(json.dumps({"blocked": problem, "input_sent": False}), flush=True)
            return 1
        kind = "single" if args.single else "circuit" if args.circuit else "farm"
        output = (
            Path(__file__).resolve().parents[1]
            / "artifacts"
            / "farming-checks"
            / f"prepared-{kind}-{args.origin}-{time.time_ns()}"
        )
        before = proven(status)
        activity = (
            "circuit" if args.circuit else "single-platform" if args.single else "learn_moves"
        )
        print(f"Starting one {args.minutes}-minute {activity} farm from {args.origin}", flush=True)
        try:
            settings = (
                {"single_platform": True, "consumables": True}
                if args.single
                else {
                    "circuit": {"id": args.circuit, "revision": args.revision},
                    "consumables": args.consumables,
                    "require_enemy": True,
                }
                if args.circuit
                else {"learn_moves": True, **({"consumables": True} if args.consumables else {})}
            )
            result = run(api, output, area=args.area, session_minutes=args.minutes, **settings)
        except Exception as error:
            print(json.dumps({"error": str(error), "result": str(output)}), flush=True)
            result = {"outcome": "failure", "error": str(error)}
        after = result.get("after") or status
        try:
            after = api.status()
            result["after_is_current"] = True
        except Exception as error:
            result["status_error"] = str(error)
            result["after_is_current"] = False
            result["outcome"] = "failure"
            result["error"] = result.get("error") or f"final status failed: {error}"
        result["after"] = after
        print(
            json.dumps(
                {
                    "result": str(output / "result.json"),
                    "outcome": result.get("outcome"),
                    "error": result.get("error"),
                    "stop_error": result.get("stop_error"),
                    "proven_before": before,
                    "proven_after": proven(after),
                    "misses": [
                        (m.get("edge"), m.get("landed"))
                        for m in ((after.get("navigation") or {}).get("learning") or {}).get(
                            "misses", []
                        )
                    ],
                    "input_state": after.get("input_state"),
                    "stop": after.get("stop"),
                    "after_is_current": result["after_is_current"],
                    "status_error": result.get("status_error"),
                    "command_seconds": round(time.monotonic() - started, 2),
                }
            ),
            flush=True,
        )
        if result.get("outcome") == "nothing_left":
            print("Nothing left to do from here; stopped cleanly. No alarm.", flush=True)
            return 0
        if result.get("outcome") != "functional_success":
            try:
                api.command("stop")
            except Exception as error:
                result["stop_error"] = str(error)
            try:
                output.mkdir(parents=True, exist_ok=True)
                (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            except Exception as error:
                print(json.dumps({"result_write_error": str(error)}), flush=True)
            finally:
                print("Control returned to operator. Move to safety; no retry.", flush=True)
                if not result.get("after_is_current") or not (after.get("alarm") or {}).get(
                    "active"
                ):
                    import winsound

                    winsound.PlaySound(
                        str(Path(__file__).resolve().parents[1] / "src/maplebot/static/alarm.wav"),
                        winsound.SND_FILENAME,
                    )
            return 1
        return 0
    finally:
        if owns_api and hasattr(api, "close"):
            try:
                api.close()
            except Exception as error:
                print(
                    json.dumps({"close_error": str(error), "input_release": "unverified"}),
                    flush=True,
                )


if __name__ == "__main__":
    raise SystemExit(main())
