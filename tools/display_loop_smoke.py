"""Passive display-loop timing on the calibrated game view: screenshots only, never input.

Boxes need recognition anchors from the engine, so this measures capture and terrain
alignment throughput with an empty anchor. Close nothing; the engine keeps running.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from maplebot.capture import Calibration, Capture
from maplebot.config import Config
from maplebot.display_loop import DisplayLoop, DisplaySource
from maplebot.windows import Windows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("area_id")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/display-loop-smoke"))
    args = parser.parse_args()
    config = Config.load(args.config)
    data = Path(config.capture.data_dir)
    calibration = Calibration.load(data / "calibration.json")
    windows = Windows()
    matches = [window for window in windows.list() if calibration.valid_for(window)
               and config.capture.window_title.casefold() in window.title.casefold()]
    if len(matches) != 1:
        raise SystemExit("Calibrated game window not found exactly once")
    area = json.loads((data / "areas" / f"{args.area_id}.json").read_text("utf-8"))
    view = next((item for item in area["views"]
                 if item["id"] == (area.get("minimap_calibration") or {}).get("view_id")),
                area["views"][0])
    reference = cv2.imread(str(data / "areas" / "frames" / f"{view['image']}.png"))
    capture = Capture(windows)
    first, _, _ = capture.window(matches[0].hwnd, calibration)
    anchor = {"frame": {"id": "smoke:0", "captured_at": time.time()}, "player": None,
              "monsters": [], "target": None, "position": None}
    source = DisplaySource("smoke:source:0", 0, matches[0].hwnd, None, calibration,
                           (anchor, first), (area["id"], area["revision"], reference,
                                             view["origin"]["x"], view["origin"]["y"],
                                             view["scale"]))
    loop = DisplayLoop(lambda: source, config.capture.display_fps)
    args.output.mkdir(parents=True, exist_ok=True)
    packets, began = [], time.perf_counter()
    while time.perf_counter() - began < args.seconds:
        tick = time.perf_counter()
        packet = loop.step(capture)
        packets.append(packet)
        time.sleep(max(0.0, loop.interval - (time.perf_counter() - tick)))
    elapsed = time.perf_counter() - began
    capture.close()
    timing = {key: np.array([packet["timing"][key] for packet in packets if packet])
              for key in ("capture_ms", "terrain_ms", "tracks_ms")}
    times = np.array([packet["frame"]["captured_at"] for packet in packets if packet])
    result = {
        "area": area["name"], "seconds": round(elapsed, 2), "packets": len(packets),
        "packets_per_second": round(len(packets) / elapsed, 1),
        "gap_ms_p50_p95": [round(float(np.percentile(np.diff(times) * 1000, q)), 1)
                           for q in (50, 95)],
        "terrain_valid": sum(bool(packet and packet["terrain"]) for packet in packets),
        **{f"{key}_p50_p95": [round(float(np.percentile(values, q)), 2) for q in (50, 95)]
           for key, values in timing.items()},
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=1), "utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
