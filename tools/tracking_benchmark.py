"""Offline player-tracking benchmark over recorded frames; no capture, engine or input.

Scenarios replay saved combat clips through TemplateDetector exactly as the runtime calls it,
optionally editing frames to add a known occlusion. Truth is the recorded name-tag-confirmed
player box; real occlusions interpolate it between the confirmed frames on either side.
Run once per source tree (`--src`) to compare before/after builds on identical frames.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "data/recordings"
BRIDGE = "session-1793525013022755400-combat"
LADDER = "session-1793524444673474500-combat"
# Occluder patches cut from real frames of this map: the log bridge and a second player.
LOG = (BRIDGE, "00000258.png", (560, 548, 220, 52))
STRANGER = (BRIDGE, "00000258.png", (972, 150, 66, 88))


def load(clip: str, first: int, last: int) -> list[dict]:
    rows = [json.loads(line) for line in (RECORDINGS / clip / "decisions.jsonl").open()]
    rows = [r for r in rows if first <= int(r["frame"][:8]) <= last]
    for row in rows:
        row["image"] = cv2.imread(str(RECORDINGS / clip / row["frame"]))
        player = row.get("player") or {}
        confirmed = (player.get("template", "").startswith("nametag:") and not player.get("tracked")
                     and player.get("confidence", 0) >= .9)
        row["anchor"] = player["box"] if confirmed else None
    return [r for r in rows if r["image"] is not None]


def interpolate(rows: list[dict], limit: float = 4.0) -> None:
    """Truth for unconfirmed frames: linear between confirmed frames at most `limit` s apart."""
    anchors = [(i, r) for i, r in enumerate(rows) if r["anchor"]]
    for row in rows:
        row["truth"] = row["anchor"]
    for (i, a), (j, b) in zip(anchors, anchors[1:], strict=False):
        t0, t1 = a["policy_input"]["now"], b["policy_input"]["now"]
        if j - i < 2 or t1 - t0 > limit:
            continue
        for row in rows[i + 1:j]:
            f = (row["policy_input"]["now"] - t0) / (t1 - t0)
            row["truth"] = {k: a["anchor"][k] + f * (b["anchor"][k] - a["anchor"][k])
                            for k in ("x", "y", "width", "height")}


def patch(spec) -> np.ndarray:
    clip, frame, (x, y, w, h) = spec
    return cv2.imread(str(RECORDINGS / clip / frame))[y:y + h, x:x + w].copy()


def erase(image: np.ndarray, box: dict) -> None:
    """Remove the player and name tag by inpainting: a complete disappearance."""
    mask = np.zeros(image.shape[:2], np.uint8)
    x, y, w, h = (int(box[k]) for k in ("x", "y", "width", "height"))
    cv2.rectangle(mask, (x - 8, y - 8), (x + w + 8, y + h + 24), 255, -1)
    image[:] = cv2.inpaint(image, mask, 5, cv2.INPAINT_TELEA)


def cover(image: np.ndarray, box: dict, piece: np.ndarray, fraction: float) -> None:
    """Paste a foreground patch over the lower `fraction` of the player and its name tag."""
    x, y, w, h = (int(box[k]) for k in ("x", "y", "width", "height"))
    top = y + round(h * (1 - fraction))
    bottom = y + h + 22
    left = x + w // 2 - piece.shape[1] // 2
    scaled = cv2.resize(piece, (piece.shape[1], bottom - top))
    x0, x1 = max(0, left), min(image.shape[1], left + scaled.shape[1])
    image[top:bottom, x0:x1] = scaled[:, x0 - left:x1 - left]


def place(image: np.ndarray, box: dict, piece: np.ndarray, dx: int) -> None:
    """A second player standing `dx` px beside the truth box, feet level."""
    x, feet = int(box["x"]) + dx, int(box["y"] + box["height"])
    y = feet - piece.shape[0] + 20
    image[y:y + piece.shape[0], x:x + piece.shape[1]] = piece


def scenarios() -> dict[str, tuple[list[dict], tuple[int, int] | None]]:
    """name -> (frames, occluded index range or None for real-occlusion clips)."""
    found = {}
    real = load(BRIDGE, 240, 270)
    interpolate(real)
    found["bridge_real"] = (real, (15, 25))  # behind the log: frames 255-264
    ladder = load(LADDER, 780, 815)
    interpolate(ladder)
    found["ladder_top_tag_crossed"] = (ladder, (26, 36))  # ladder top crosses the name tag
    log, stranger = patch(LOG), patch(STRANGER)
    for name, edit in (
            ("synthetic_bridge_lower60", lambda img, box: cover(img, box, log, .6)),
            ("synthetic_heavy_cover85", lambda img, box: cover(img, box, log, .85)),
            ("synthetic_disappear", erase)):
        frames = load(BRIDGE, 213, 253)
        interpolate(frames)
        for row in frames[12:24]:
            if row["truth"]:
                edit(row["image"], row["truth"])
        found[name] = (frames, (12, 24))
    frames = load(BRIDGE, 213, 253)
    interpolate(frames)
    for i, row in enumerate(frames):
        if row["truth"] and 6 <= i < 30:
            place(row["image"], row["truth"], stranger, 70)
            if 12 <= i < 24:
                erase(row["image"], row["truth"])  # our player gone; the stranger stays
    found["nearby_player_hijack"] = (frames, (12, 24))
    # Worst case: an identically dressed player (our own sprite, no name tag) 70 px away.
    frames = load(BRIDGE, 213, 253)
    interpolate(frames)
    for i, row in enumerate(frames):
        t = row["truth"]
        if t and 6 <= i < 30:
            x, y, w, h = (int(t[k]) for k in ("x", "y", "width", "height"))
            clone = row["image"][y - 4:y + h, x - 4:x + w + 4].copy()
            if 12 <= i < 24:
                erase(row["image"], t)
            row["image"][y - 4:y + h, x + 66:x + w + 74] = clone
    found["identical_clone_70px"] = (frames, (12, 24))
    return found


def run(src: Path, label: str, identity_rule: str) -> dict:
    sys.path.insert(0, str(src))
    sys.path.insert(1, str(ROOT))
    from maplebot.perception import TemplateDetector
    from maplebot.reacquisition import Reacquisition
    from tools.perception_benchmark import percentile, perception_config, reset, settle_map

    detector = TemplateDetector(ROOT / "data/templates", perception_config(ROOT / "config.toml"))
    threshold = detector.config.confidence
    report = {"label": label, "src": str(src), "identity_rule": identity_rule,
              "input_sent": False, "scenarios": {}}
    for name, (frames, occluded) in scenarios().items():
        reset(detector)
        if hasattr(detector, "confirmed_sprites"):
            detector.confirmed_sprites = type(detector.confirmed_sprites)()
        detector.misses, detector.lookalike_at = 0, float("-inf")
        settle_map(detector, frames[0]["image"])
        detector.taught_map = True
        recovery, rows = Reacquisition(), []
        for row in frames:
            monsters = row.get("mode") not in {"navigation", "navigation_wait"}
            start = time.perf_counter()
            obs = detector.detect(row["image"], row["policy_input"]["now"], monsters=monsters)
            ms = (time.perf_counter() - start) * 1000
            p = obs.player
            fresh = p is not None and not p.tracked and p.confidence >= threshold
            if not fresh:
                identity = None
            elif identity_rule == "template":
                identity = p.template.removesuffix(":tag-only")
            else:
                identity = getattr(p, "identity", None) or p.template.removesuffix(":tag-only")
            step = recovery.step(identity, row["policy_input"]["now"])
            if step.state == "resume":
                recovery.resumed()
            error = None
            if p and row["truth"]:
                t = row["truth"]
                error = float(np.hypot(p.box.center[0] - (t["x"] + t["width"] / 2),
                                       p.box.feet - (t["y"] + t["height"])))
            rows.append({"frame": row["frame"], "now": row["policy_input"]["now"], "ms": ms,
                         "player": None if p is None else {
                             "box": [p.box.x, p.box.y, p.box.width, p.box.height],
                             "template": p.template, "tracked": p.tracked,
                             "confidence": p.confidence, "identity": getattr(p, "identity", None)},
                         "truth": bool(row["truth"]), "error_px": error, "step": step.state})
            if step.state == "stop":
                break
        report["scenarios"][name] = metrics(rows, occluded, percentile)
        report["scenarios"][name]["frames"] = rows
    detector.pool.shutdown()
    return report


def metrics(rows: list[dict], occluded, percentile) -> dict:
    truth = [r for r in rows if r["truth"]]
    located = [r for r in truth if r["error_px"] is not None]
    errors = [r["error_px"] for r in located]
    stop = next((r["frame"] for r in rows if r["step"] == "stop"), None)
    end = occluded[1] if occluded else None
    recovered = None
    if end is not None and end < len(rows) and not stop:
        later = [r for r in rows[end:] if r["step"] in {"ok", "resume", "pass"}]
        if later:
            recovered = round(later[0]["now"] - rows[end]["now"], 3)
    ms = [r["ms"] for r in rows]
    return {
        "frames": len(rows), "truth_frames": len(truth),
        "located_rate": round(len(located) / len(truth), 3) if truth else None,
        "within_20px_rate": (round(sum(e <= 20 for e in errors) / len(truth), 3)
                             if truth else None),
        "median_error_px": round(float(np.median(errors)), 1) if errors else None,
        "p95_error_px": round(percentile(errors, .95), 1) if errors else None,
        "hijacked_frames": sum(e > 60 for e in errors),
        "paused_frames": sum(r["step"] in {"pause", "wait"} for r in rows),
        "stopped_at": stop, "recovery_s_after_occlusion": recovered,
        "ms_p50": round(percentile(ms, .5), 1), "ms_p95": round(percentile(ms, .95), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=ROOT / "src")
    parser.add_argument("--label", default="current")
    parser.add_argument("--identity-rule", choices=("template", "resolved"), default="resolved")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.src.resolve(), args.label, args.identity_rule)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), "utf-8")
    for name, values in report["scenarios"].items():
        print(name, {k: v for k, v in values.items() if k != "frames"}, flush=True)


if __name__ == "__main__":
    main()
