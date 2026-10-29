"""Unattended navigation checks. --check is read-only; --run starts supervised-equivalent routes.

Runs under the operator's standing permission in AGENTS.md: each route goes through the
engine's normal nav_go command and every existing gate. The batch stops at the first route
that does not arrive, sends Stop at the end, and writes one result file with clip paths.
"""
import argparse
import json
import re
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROUTE_SECONDS = 70  # countdown (3 s) plus the navigator's 60 s route budget, with margin
READY_SECONDS = 8  # wait this long for a confirmed position on the origin before a route


class Debugger:
    def __init__(self, base: str = "http://127.0.0.1:8765"):
        self.base = base
        with urlopen(self.base + "/", timeout=2) as response:
            self.token = re.search(r"[A-Za-z0-9_\-]{43}", response.read().decode()).group()

    def status(self) -> dict:
        with urlopen(self.base + "/api/status", timeout=2) as response:
            return json.load(response)

    def command(self, name: str, payload: dict | None = None) -> dict:
        status = self.status()
        envelope = {"schema_version": 1, "session_id": status["session_id"],
                    "command_id": uuid.uuid4().hex, "issued_at": time.time(),
                    "command_epoch": status["command_epoch"],
                    "expected_frame_id": status["frame"]["id"], "name": name,
                    "payload": payload or {}}
        request = Request(self.base + "/api/v1/command", data=json.dumps(envelope).encode(),
                          headers={"X-Debug-Token": self.token,
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as error:
            with error:
                body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{name} rejected: {body.replace(self.token, '[redacted]')}") \
                from error


def readiness(status: dict) -> str | None:
    """Why no route may start now, ignoring route-specific checks."""
    if status.get("capture_only"):
        return "Capture-only session: restart with tools/restart_engine.ps1 -EnableGameplayInput"
    if status["mode"] != "capture":
        return "Bot must be Off"
    if not status.get("focused"):
        return "Focus MapleStory"
    position = status.get("position") or {}
    if not position.get("area_id"):
        return "Track a map first"
    if not (status.get("navigation") or {}).get("map"):
        return "Load navigation routes first"
    return None


def targets(status: dict) -> list[str]:
    """Routable platforms other than the current one, in saved map order."""
    nav = status["navigation"]["map"]
    here = (status.get("position") or {}).get("surface_id")
    return [n["id"] for n in nav["nodes"]
            if n["kind"] == "platform" and not n["excluded"] and n["id"] != here]


def compact(status: dict) -> dict:
    nav = status.get("navigation") or {}
    return {"mode": status.get("mode"), "stage": nav.get("stage"), "reason": nav.get("reason"),
            "surface": (status.get("position") or {}).get("surface_id"),
            "proven": (nav.get("map") or {}).get("proven_edges"), "stop": status.get("stop")}


def run(api, output: Path, *, limit: int, chosen: list[str] | None = None,
        clock=time.monotonic, sleep=time.sleep) -> dict:
    status = api.status()
    problem = readiness(status)
    if problem:
        raise RuntimeError(problem)
    api.command("nav_refresh")
    status = api.status()
    queue = list(chosen) if chosen else targets(status)
    routes, failure = [], None
    try:
        for target in queue[:limit]:
            row = {"target": target, "before": compact(api.status())}
            routes.append(row)
            waited = clock()
            # nav_go plans from the current platform; wait out brief name-tag dropouts.
            while not ((api.status().get("position") or {}).get("surface_id") or None):
                if clock() - waited >= READY_SECONDS:
                    failure = row["outcome"] = "not ready: platform unknown"
                    break
                sleep(.25)
            if failure:
                break
            try:
                api.command("nav_go", {"target": target, "opt_in": True})
            except RuntimeError as error:
                row["outcome"] = f"refused: {error}"
                failure = row["outcome"]
                break
            started = clock()
            while clock() - started < ROUTE_SECONDS:
                sleep(.25)
                sample = api.status()
                if sample["mode"] not in {"navigation", "navigation_wait"}:
                    break
            else:
                api.command("stop")
                sample = api.status()
            row["after"] = compact(sample)
            row["seconds"] = round(clock() - started, 2)
            if row["after"]["stage"] == "arrived":
                row["outcome"] = "arrived"
                sleep(1)  # let the position settle before planning the next route
            else:
                row["outcome"] = "stopped"
                failure = (row["after"]["reason"]
                           or (row["after"]["stop"] or {}).get("message") or "stopped")
                break
    finally:
        try:
            api.command("stop")
        except Exception as error:  # the run result still records what happened
            failure = failure or f"final stop failed: {error}"
        output.mkdir(parents=True, exist_ok=False)
        result = {"limit": limit, "routes": routes, "failure": failure,
                  "arrived": sum(r.get("outcome") == "arrived" for r in routes),
                  "proven_after": compact(api.status())["proven"]}
        (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--routes", type=int, default=6, help="at most this many routes")
    parser.add_argument("--targets", help="comma-separated platform IDs, in order")
    parser.add_argument("--focus", action="store_true",
                        help="Request game focus through the engine before --run")
    parser.add_argument("--focus-click", action="store_true",
                        help="Allow one verified title-bar click if API focus fails")
    args = parser.parse_args()
    if args.focus_click and not args.focus:
        parser.error("--focus-click requires --focus")
    if args.focus and not args.run:
        parser.error("--focus requires --run; --check remains read-only")
    api = Debugger()
    if args.check:
        status = api.status()
        print(json.dumps({"ready": readiness(status), "input_sent": False,
                          "targets": targets(status) if not readiness(status) else []}))
        return
    if args.focus:
        result = api.command("focus_game", {"click_fallback": args.focus_click})
        if not result.get("focused"):
            raise RuntimeError("Windows declined game focus; no navigation started")
        deadline = time.monotonic() + 3
        while not api.status().get("focused"):
            if time.monotonic() >= deadline:
                raise RuntimeError("Game focus was not confirmed; no navigation started")
            time.sleep(.1)
    output = (Path(__file__).resolve().parents[1] / "artifacts" / "navigation-checks"
              / time.strftime("%Y%m%d-%H%M%S"))
    result = run(api, output, limit=max(1, args.routes),
                 chosen=args.targets.split(",") if args.targets else None)
    print(json.dumps({"evidence": str(output / "result.json"), "arrived": result["arrived"],
                      "routes": len(result["routes"]), "failure": result["failure"],
                      "proven_after": result["proven_after"]}))
    if result["failure"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
