"""Mushroom Park movement checks through existing engine commands; never takes focus.

--check sends no commands and writes no files. --run saves every attempt, including
preflight refusals. A failed movement cannot repeat against unchanged code/map/bindings.
"""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

from maplebot.contracts import FRESH_FRAME_SECONDS
from maplebot.navigation import RouteMap, map_hash, surface_y
from tools.navigation_check import ROUTE_SECONDS, Debugger

TOWN_ID = 100000200
ROOT = Path(__file__).resolve().parents[1]
PROBE_SECONDS = 8


def profile_for_town(directory: Path) -> dict:
    profiles = [json.loads(path.read_text("utf-8")) for path in directory.glob("*.json")]
    matches = [p for p in profiles if p.get("public_map", {}).get("id") == TOWN_ID]
    if len(matches) != 1:
        raise ValueError("Prepare exactly one imported Mushroom Park profile (100000200)")
    return matches[0]


def blocker(status: dict, profile: dict, *, session=None, settled=True,
            allow_rope=False) -> str | None:
    if status.get("capture_only"):
        return "Capture-only session; use an explicitly input-capable restart"
    if session is not None and status.get("session_id") != session:
        return "Engine session changed"
    if not status.get("focused"):
        return "Game is not focused; stop without taking focus"
    if status.get("alarm", {}).get("active"):
        return "Active alarm; inspect its clip before operator acknowledgement"
    if profile.get("public_map", {}).get("id") != TOWN_ID:
        return "Expected Mushroom Park (100000200)"
    position = status.get("position") or {}
    if position.get("area_id") != profile["id"]:
        return "Wrong tracked map; expected the saved Mushroom Park area"
    nav = (status.get("navigation") or {}).get("map") or {}
    if (nav.get("area_id"), nav.get("revision"), nav.get("map_hash")) != (
            profile["id"], profile["revision"], map_hash(profile)):
        return "Navigation map revision/hash does not match the saved park"
    frame = status.get("frame") or {}
    age = frame.get("age_ms")
    if (not frame.get("available") or not isinstance(age, (int, float))
            or not math.isfinite(age) or not 0 <= age <= FRESH_FRAME_SECONDS * 1000):
        return "Recognition frame is stale or unavailable"
    player = status.get("player") or {}
    confidence = player.get("confidence", 0)
    if (not player or player.get("tracked") or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or confidence < .9):
        return "Player is not freshly recognized"
    if (position.get("stale") is not False or position.get("provisional")
            or position.get("held") or not position.get("marker")
            or not position.get("canvas") or not position.get("calibrated")):
        return "Park minimap/position is missing, stale or unconfirmed"
    if settled:
        if status.get("mode") != "capture":
            return "Bot must be Off"
        if status.get("active_probe") or status.get("area_editing") or status.get("calibrating"):
            return "Finish the active probe or editing first"
        kinds = {"platform", "rope"} if allow_rope else {"platform"}
        if position.get("kind") not in kinds or not position.get("surface_id"):
            return "Stand on a confirmed park platform or the expected ladder"
        if position.get("feet") is None:
            return "Confirmed player feet are unavailable"
    return None


def world_feet(status: dict, profile: dict) -> tuple[float, float]:
    feet = status["position"]["feet"]
    fit = profile["public_map"]["world"]
    return tuple((feet[i] - fit[axis][1]) / fit[axis][0] for i, axis in enumerate(("x", "y")))


def start_spot(status: dict, profile: dict) -> str | None:
    x, y = world_feet(status, profile)
    if not (3100 <= x <= 3240 and abs(y - 574) <= 20):
        return "Stand on lower ground 100 px left of the only ladder (world x3190, y574)"
    return None


def ladder_round_trip(profile: dict, status: dict) -> tuple[str, str]:
    graph = RouteMap.computed(profile)
    origin = status["position"]["surface_id"]
    ropes = {r["id"] for r in profile["ropes"] if r.get("name", "").startswith("Ladder")}
    candidates = []
    for platform in profile["platforms"]:
        target = platform["id"]
        if target == origin:
            continue
        try:
            up = graph.plan(origin, target, origin_feet=status["position"]["feet"])
        except ValueError:
            continue
        for rope in (r for r in profile["ropes"] if r["id"] in ropes):
            key = rope["id"]
            if (not any(e.kind == "climb" and e.target == key for e in up.edges)
                    or not any(e.kind == "climb" and e.source == key for e in up.edges)):
                continue
            try:
                # A direct return may choose a drop. Pin descent through the same ladder.
                grip, down = graph.plan(target, key), graph.plan(key, origin)
            except ValueError:
                continue
            if all(e.kind == "climb" for e in (*grip.edges, *down.edges)):
                distance = abs(surface_y(platform, rope["start"]["x"]) - rope["start"]["y"])
                candidates.append((distance, target, key))
    if candidates:
        _, target, rope = min(candidates)
        return target, rope
    raise ValueError("No ladder round trip passes the existing home/route safety gates")


def ladder_target(profile: dict, status: dict) -> str:
    return ladder_round_trip(profile, status)[0]


def compact(status: dict) -> dict:
    return {k: status.get(k) for k in (
        "session_id", "mode", "focused", "frame", "player", "position", "navigation",
        "stop", "last_action", "active_probe", "action_outcome")}


class Check:
    def __init__(self, api, profile, *, clock=time.monotonic, sleep=time.sleep):
        self.api, self.profile, self.clock, self.sleep = api, profile, clock, sleep
        self.session = None
        self.rows = []
        self.started = False

    def status(self, *, settled=False, allow_rope=False):
        value = self.api.status()
        if problem := blocker(value, self.profile, session=self.session, settled=settled,
                              allow_rope=allow_rope):
            raise RuntimeError(problem)
        return value

    def clip(self, row):
        try:
            row["clip"] = self.api.command("clip")["path"]
        except Exception as error:
            row["clip_error"] = str(error)

    def probe(self, action):
        before = self.status(settled=True)
        ready = before.get("readiness", {}).get(f"probe:{action}", {})
        if not ready.get("ready"):
            raise RuntimeError(ready.get("reason") or f"{action} probe is not ready")
        if problem := start_spot(before, self.profile):
            raise RuntimeError(problem)
        origin = before["position"]["surface_id"]
        x0, y0 = world_feet(before, self.profile)
        row = {"action": action, "before": compact(before), "samples": [], "passed": False}
        self.rows.append(row)
        started = self.clock()
        try:
            # A lost HTTP response cannot prove that the engine rejected the request.
            self.started = True
            probe = self.api.command("probe", {"action": action})
            while self.clock() - started < PROBE_SECONDS:
                self.sleep(.1)
                sample = self.status()
                row["samples"].append(compact(sample))
                if sample["mode"] not in {"probe_wait", "probe_queued", "probe_confirm"}:
                    raise RuntimeError("Probe stopped before its movement was confirmed")
                pos = sample["position"]
                if (sample["mode"] == "probe_confirm" and pos.get("kind") == "platform"
                        and pos.get("surface_id") == origin and pos.get("feet") is not None):
                    x, y = world_feet(sample, self.profile)
                    if action in {"left", "right"}:
                        moved = (x - x0) * (-1 if action == "left" else 1)
                        passed = moved >= 2 and abs(y - y0) <= 20
                    else:
                        heights = [s["player"]["box"]["y"] + s["player"]["box"]["height"]
                                   for s in row["samples"]]
                        passed = max(heights) - min(heights) >= 12 and abs(y - y0) <= 20
                    if passed:
                        confirmed = self.api.command("confirm_probe", {
                            "id": probe["id"], "generation": probe["generation"]})
                        if confirmed.get("confirmed") is not True:
                            raise RuntimeError("Engine did not accept probe confirmation")
                        row["passed"] = True
                        return
            self.api.command("reject_probe", {"id": probe["id"],
                                              "generation": probe["generation"]})
            raise RuntimeError(f"{action} movement/settled landing was not observed")
        finally:
            row["seconds"] = round(self.clock() - started, 3)
            self.clip(row)
            self.api.command("stop")

    def route(self, target, *, from_rope=None):
        before = self.status(settled=True, allow_rope=from_rope is not None)
        if from_rope is not None and before["position"]["surface_id"] != from_rope:
            raise RuntimeError("Expected confirmed grip on the round-trip ladder")
        if target == before["position"]["surface_id"]:
            raise RuntimeError("Current-platform no-op is not a movement test")
        if not target:
            raise RuntimeError("No route target selected")
        row = {"target": target, "before": compact(before), "samples": [], "passed": False}
        self.rows.append(row)
        started = self.clock()
        try:
            self.started = True
            self.api.command("nav_go", {"target": target, "opt_in": True})
            while self.clock() - started < ROUTE_SECONDS:
                self.sleep(.1)
                sample = self.status()
                row["samples"].append(compact(sample))
                if sample["mode"] not in {"navigation", "navigation_wait"}:
                    break
            else:
                raise RuntimeError("Route exceeded its existing time budget")
            if (sample["mode"] != "capture" or sample["navigation"]["stage"] != "arrived"
                    or sample["position"].get("surface_id") != target):
                raise RuntimeError(sample["navigation"].get("reason") or "No settled arrival")
            row["passed"] = True
        finally:
            row["seconds"] = round(self.clock() - started, 3)
            self.clip(row)
            self.api.command("stop")


def code_revision(profile: dict, status: dict) -> str:
    digest = hashlib.sha256()
    for path in [Path(__file__), *sorted((ROOT / "src/maplebot").glob("*.py"))]:
        digest.update(path.read_bytes())
    digest.update(json.dumps([profile, status.get("bindings")], sort_keys=True).encode())
    return digest.hexdigest()


def run(api, profile, output: Path, *, clock=time.monotonic, sleep=time.sleep) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    runner = Check(api, profile, clock=clock, sleep=sleep)
    result = {"town_id": TOWN_ID, "steps": runner.rows, "failure": None,
              "movement_requested": False, "setup_seconds": 0, "test_seconds": 0}
    began = clock()
    test_started = None
    try:
        initial = api.status()
        result["before"] = compact(initial)
        if problem := blocker(initial, profile):
            raise RuntimeError(problem)
        runner.session = initial["session_id"]
        if problem := start_spot(initial, profile):
            raise RuntimeError(problem)
        target, rope = ladder_round_trip(profile, initial)
        origin = initial["position"]["surface_id"]
        revision = result["revision"] = code_revision(profile, initial)
        for previous in output.parent.glob("*/result.json"):
            old = json.loads(previous.read_text("utf-8"))
            if (old.get("failure") and old.get("movement_requested")
                    and old.get("revision") == revision):
                raise RuntimeError(f"Unchanged failed movement; inspect {previous} and fix cause")
        result["setup_seconds"] = round(clock() - began, 3)
        test_started = clock()
        for action in ("left", "right", "jump"):
            runner.probe(action)
        runner.route(target)
        runner.route(rope)
        runner.route(origin, from_rope=rope)
    except Exception as error:
        result["failure"] = str(error)
    finally:
        result["movement_requested"] = runner.started
        if test_started is None:
            result["setup_seconds"] = round(clock() - began, 3)
        else:
            result["test_seconds"] = round(clock() - test_started, 3)  # Includes countdowns.
        # Preflight refusals send no commands. Once a probe/route was requested, always Stop.
        if runner.rows:
            try:
                result["stop_response"] = api.command("stop")
            except Exception as error:
                result["stop_error"] = str(error)
                result["failure"] = result["failure"] or "Final Stop failed"
        try:
            result["after"] = compact(api.status())
            if runner.started and result["after"].get("mode") != "capture":
                result["failure"] = result["failure"] or "Engine did not finish Off"
        except Exception as error:
            result["after_error"] = str(error)
            result["failure"] = result["failure"] or "Final status unavailable"
        (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    output = ROOT / "artifacts/town-checks" / str(time.time_ns())
    initial = None
    try:
        api = Debugger()
        initial = api.status()
        if not initial.get("focused"):
            raise RuntimeError("Game is not focused; stop without taking focus")
        profile = profile_for_town(ROOT / "data/areas")
        if args.check:
            sample = api.status()
            problem = blocker(sample, profile)
            if not problem:
                problem = start_spot(sample, profile)
            target = None
            if not problem:
                target = ladder_target(profile, sample)
            print(json.dumps({"blocker": problem, "target": target, "input_sent": False}))
            if problem:
                raise SystemExit(1)
            return
        result = run(api, profile, output)
    except Exception as error:
        result = {"failure": str(error), "movement_requested": False,
                  "before": compact(initial) if initial else None}
        if args.run:
            output.mkdir(parents=True, exist_ok=True)
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"failure": result["failure"], "evidence": str(output / "result.json")
                      if args.run else None, "movement_requested": result["movement_requested"]}))
    if result["failure"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
