"""Labelled manual hit checks: GET-only evidence capture, never gameplay input."""

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from .combat_readiness import summarize
from .config import Config

KEYS = {"attack": "space", "skill": "ctrl"}


def get(base: str, path: str) -> bytes:
    with urlopen(base + path, timeout=3) as response:
        return response.read()


def validate(status: dict, action: str) -> None:
    if status.get("mode") != "capture" or status.get("active_probe"):
        raise ValueError("Set Bot activity to Off and finish any active probe first")
    if status.get("bindings", {}).get(action) != KEYS[action]:
        raise ValueError(f"Loaded {action} binding is not {KEYS[action]}; check setup")


def collect(base: str, config: Config, action: str, output: Path, seconds: float,
            *, check: bool = False) -> dict:
    initial = json.loads(get(base, "/api/v1/status"))
    validate(initial, action)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "action": action, "key_label": KEYS[action],
        "purpose": "installation_check" if check else "manual_hit_check",
        "session_id": initial["session_id"], "started_at": time.time(),
        "key_label_source": "Operator-selected check, not a recorded keypress",
        "hit_confirmed": None, "samples": 0, "pictures": 0,
        "stop_reason": "Capture window complete",
    }
    deadline = time.monotonic() + seconds
    seen = set()
    try:
        with (output / "observations.jsonl").open("x", encoding="utf-8") as log:
            while True:
                status = json.loads(get(base, "/api/v1/status"))
                validate(status, action)
                if status["session_id"] != manifest["session_id"]:
                    raise ValueError("Engine session changed; review this check before repeating")
                # Live drawings can be ahead of PNG encoding. The top-level
                # detections are paired with the published picture we download.
                paired = {**status, "live_detections": None}
                row = summarize(paired, config, time.time())
                frame_id = row["frame_id"]
                if frame_id and frame_id not in seen:
                    seen.add(frame_id)
                    picture = f"{manifest['samples']:04d}.png"
                    row.update(key_label=KEYS[action], picture=None)
                    try:
                        raw = get(base, "/api/v1/frame?" + urlencode({"id": frame_id, "raw": 1}))
                    except HTTPError as error:
                        if error.code != 409:
                            raise
                        row["picture_unavailable"] = "Frame superseded before download"
                    else:
                        (output / picture).write_bytes(raw)
                        row["picture"] = picture
                        manifest["pictures"] += 1
                    # Preserve every detected enemy, including those outside platform tolerance.
                    row["detections"] = {
                        key: status.get(key) for key in ("frame", "player", "monsters")
                    }
                    log.write(json.dumps(row) + "\n")
                    log.flush()
                    manifest["samples"] += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.1, remaining))
    except BaseException as error:
        manifest["stop_reason"] = str(error) or type(error).__name__
        raise
    finally:
        manifest["finished_at"] = time.time()
        (output / "check.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=KEYS, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true", help="One-second input-free install check")
    args = parser.parse_args()
    config = Config.load(args.config)
    base = f"http://127.0.0.1:{args.port}"
    validate(json.loads(get(base, "/api/v1/status")), args.action)
    label = KEYS[args.action]
    if not args.check:
        print(f"{label.upper()} ONLY: Bot Off; bow/ammo ready; face a boxed same-platform enemy.")
        print("Close game chat. After Enter, focus the game; wait 3 seconds.")
        print(f"Then press {label.upper()} once. Watch for damage; no other attack key.")
        print("Stop after that attempt, or skip it if player/enemy recognition is lost.")
        input("Press Enter when positioned. Capture lasts 10 seconds after the countdown. ")
        for remaining in (3, 2, 1):
            print(remaining, flush=True)
            time.sleep(1)
    output = Path("artifacts") / f"bowman-hit-{label}-{time.time_ns()}"
    print("Capturing pictures and distances; this tool sends no keys.", flush=True)
    result = collect(base, config, args.action, output, 1 if args.check else 10, check=args.check)
    print(f"Saved {result['pictures']} pictures: {output.resolve()}")
    if args.check:
        print("Read-only installation check complete; no attack requested.")
    else:
        print("Finished. Report hit / miss / unclear for this key; keep Bot Off.")


if __name__ == "__main__":
    main()
