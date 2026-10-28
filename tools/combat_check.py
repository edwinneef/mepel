"""Prepared one-shot combat check. --check is read-only; --run starts gameplay."""
import argparse
import json
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class Debugger:
    def __init__(self):
        self.base = "http://127.0.0.1:8765"
        with urlopen(self.base + "/", timeout=2) as response:
            self.token = re.search(r"[A-Za-z0-9_\-]{43}", response.read().decode()).group()

    def status(self):
        with urlopen(self.base + "/api/status", timeout=2) as response:
            return json.load(response)

    def command(self, name, status):
        envelope = {
            "schema_version": 1, "session_id": status["session_id"],
            "command_id": uuid.uuid4().hex, "issued_at": time.time(),
            "command_epoch": status["command_epoch"],
            "expected_frame_id": status["frame"]["id"], "name": name, "payload": {},
        }
        request = Request(self.base + "/api/v1/command", data=json.dumps(envelope).encode(),
                          headers={"X-Debug-Token": self.token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=2) as response:
                return json.load(response)
        except HTTPError as error:
            with error:
                body = error.read().decode("utf-8", errors="replace")
            body = body.replace(self.token, "[redacted]")
            raise RuntimeError(f"{name} rejected (HTTP {error.code}): {body}") from error


def blocker(status):
    if status["mode"] != "capture":
        return "Bot must be Off"
    if not status["readiness"]["combat"]["ready"]:
        return status["readiness"]["combat"]["reason"]
    if not status.get("focused"):
        return "Focus MapleStory"
    if status["attack_setup"]["profile"] != "classic_2h_sword":
        return "Expected the saved Broadsword preset"
    player = status.get("player")
    if not player or player.get("tracked") or player["confidence"] < .9:
        return "Wait for a fresh confirmed player"
    feet = player["box"]["y"] + player["box"]["height"]
    if not any(not m.get("tracked") and m["confidence"] >= .9
               and abs(m["box"]["y"] + m["box"]["height"] - feet) <= 18
               for m in status.get("monsters", [])):
        return "No fresh same-platform enemy"
    return None


def compact(status):
    return {key: status.get(key) for key in (
        "session_id", "mode", "state", "reason", "focused", "frame", "player", "monsters",
        "last_action", "action_outcome", "combat_evidence", "potion_evidence", "stop",
    )}


def run(api, output, *, clock=time.monotonic, sleep=time.sleep, timer_factory=threading.Timer):
    # All setup precedes this final read. No files, imports or user interaction before arm.
    status = api.status()
    problem = blocker(status)
    if problem:
        raise RuntimeError(problem)
    rows, stop_errors = [], []
    failure = None

    def stop():
        try:
            api.command("stop", status)
        except Exception as error:
            stop_errors.append(str(error))

    watchdog = timer_factory(13, stop)  # Three-second countdown plus at most ten seconds.
    watchdog.start()
    started = clock()
    try:
        api.command("arm", status)
        while clock() - started < 13:
            sample = api.status()
            rows.append(compact(sample))
            if sample["session_id"] != status["session_id"]:
                break
            if sample["mode"] not in {"pending_arm", "live"}:
                break
            sleep(.1)
    except Exception as error:
        failure = str(error)
        raise
    finally:
        stop()
        watchdog.cancel()
        output.mkdir(parents=True, exist_ok=False)
        result = {"before": compact(status), "samples": rows, "stop_errors": stop_errors,
                  "elapsed": clock() - started, "error": failure}
        try:
            result["after"] = compact(api.status())
        except Exception as error:
            result["after_error"] = str(error)
        finally:
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    api = Debugger()
    if args.check:
        status = api.status()
        print(json.dumps({"mode": status["mode"], "blocker": blocker(status), "input_sent": False}))
        return
    output = Path(__file__).resolve().parents[1] / "artifacts" / f"combat-check-{time.time_ns()}"
    try:
        result = run(api, output)
    except Exception as error:
        print(json.dumps({"evidence": str(output / "result.json")
                          if (output / "result.json").exists() else None, "error": str(error)}))
        raise SystemExit(1) from None
    after = result.get("after", {})
    print(json.dumps({"evidence": str(output / "result.json"), "mode": after.get("mode"),
                      "stop": after.get("stop"), "stop_errors": result["stop_errors"],
                      "after_error": result.get("after_error")}))
    if result["stop_errors"] or result.get("after_error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
