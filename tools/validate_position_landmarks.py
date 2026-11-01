"""Offline horizontal position validation against independently annotated scene landmarks."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from maplebot.map_alignment import PositionInterval, align
from maplebot.meowdb import load_source
from maplebot.scene_anchors import SceneAnchor


def match(image, template, mask=None):
    scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED, mask=mask)
    scores = np.clip(np.nan_to_num(scores, nan=-1, posinf=-1, neginf=-1), -1, 1)
    _, best, _, at = cv2.minMaxLoc(scores)
    x, y = at
    h, w = template.shape[:2]
    scores[max(0, y - h // 2):y + h // 2 + 1,
           max(0, x - w // 2):x + w // 2 + 1] = -1
    if best < .90 or best - float(scores.max()) < .05:
        return None
    return x, y, float(best)


def metrics(errors):
    if not errors:
        return None
    values = np.abs(errors)
    return {"count": len(errors), "signed_bias_px": float(np.median(errors)),
            "p50_px": float(np.percentile(values, 50)),
            "p95_px": float(np.percentile(values, 95)), "max_px": float(max(values))}


def validate(recording, annotations, source_path, *, reference_recording=None, scene_anchor=False):
    labels = json.loads(annotations.read_text("utf-8"))
    source, digest = load_source(source_path, labels["map_id"])
    world_x = {r["x"] for r in source["ladderRopes"]}
    if any(item["world_x"] not in world_x for item in labels["landmarks"]):
        raise ValueError("Landmark coordinates are absent from the source map")
    basis = reference_recording or recording
    reference_path = basis / labels["reference"]
    if reference_path.parent != basis or len(labels["landmarks"]) < 2:
        raise ValueError("Need two independent landmarks in the recording reference")
    reference = cv2.imread(str(reference_path))
    if reference is None:
        raise ValueError("Missing landmark reference")
    public = {"id": labels["map_id"], "sha256": digest,
              "provider": source.get("provider", "dreamms")}
    anchor = SceneAnchor.load(public) if scene_anchor else None
    if scene_anchor and anchor is None:
        raise ValueError("No matching production scene anchor")
    templates = []
    for landmark in labels["landmarks"]:
        if anchor and landmark["world_x"] == anchor.record["world_x"]:
            continue  # The production landmark cannot also be its own validation truth.
        x, y, w, h = landmark["box"]
        if min(x, y) < 0 or min(w, h) < 8 or x + w > reference.shape[1] \
                or y + h > reference.shape[0]:
            raise ValueError("Invalid landmark crop")
        template = reference[y:y + h, x:x + w].copy()
        mask = None
        if bounds := landmark.get("foreground_hsv"):
            mask = cv2.inRange(cv2.cvtColor(template, cv2.COLOR_BGR2HSV),
                               tuple(bounds[0]), tuple(bounds[1]))
            if np.count_nonzero(mask) < 100:
                raise ValueError("Too few static landmark pixels")
        templates.append((landmark, template, mask))
    decisions = (recording / "decisions.jsonl").read_bytes()
    rows = [json.loads(line) for line in decisions.decode("utf-8").splitlines()]
    if not rows:
        raise ValueError("Empty recording")
    if anchor:
        if basis == recording:
            raise ValueError("Scene-anchor evaluation needs a separate recording")
        training = {json.loads(line)["capture_clock"] for line in
                    (basis / "decisions.jsonl").read_text().splitlines()}
        if any(row["capture_clock"] in training for row in rows):
            raise ValueError("Training and evaluation recordings overlap")
        if not templates:
            raise ValueError("Need a validation landmark independent of the production anchor")
    canvas = rows[0]["position"]["canvas"]
    automatic = align(reference, canvas, source["miniMap"])
    transform = automatic["transform"]
    fusion = PositionInterval()
    samples, refused = [], []
    for row in rows:
        frame = recording / row["frame"]
        if frame.parent != recording:
            raise ValueError("Frame escaped recording")
        image = cv2.imread(str(frame))
        if image is None or image.shape != reference.shape:
            fusion.reset()
            refused.append({"frame": row["frame"], "reason": "missing/resized frame"})
            continue
        offsets = []
        scores = []
        for landmark, template, mask in templates:
            found = match(image, template, mask)
            if found is not None:
                x, _, score = found
                offsets.append(x + landmark["screen_x"] - landmark["box"][0]
                               - landmark["world_x"])
                scores.append(score)
        position, player = row.get("position") or {}, row.get("player") or {}
        dot, box = position.get("marker"), player.get("box")
        camera = row.get("camera_shift")
        if (len(offsets) != len(templates) or max(offsets) - min(offsets) > 2
                or dot is None or box is None or player.get("tracked")
                or player.get("confidence", 0) < .90 or row.get("camera_confidence", 0) < .60
                or camera is None or position.get("canvas") != canvas):
            fusion.reset()
            refused.append({"frame": row["frame"], "reason": "landmarks/player/camera disagree"})
            continue
        screen = (box["x"] + box["width"] / 2, box["y"] + box["height"])
        truth_x = screen[0] - float(np.median(offsets))
        feet = tuple(transform[f"scale_{a}"] * dot[i] + transform[f"offset_{a}"]
                     for i, a in enumerate(("x", "y")))
        refined = fusion.update(feet, screen, camera, row["capture_clock"],
                                automatic["uncertainty_px"])
        anchored = anchor.locate_x(image, screen[0], feet[0]) if anchor and refined else None
        samples.append({"frame": row["frame"], "clock": row["capture_clock"],
                        "landmark_world_x": truth_x, "camera_offset_x": float(np.median(offsets)),
                        "landmark_agreement_px": max(offsets) - min(offsets),
                        "min_match_score": min(scores), "raw_x": feet[0],
                        "raw_error_px": feet[0] - truth_x,
                        "refined_x": refined[0][0] if refined else None,
                        "refined_error_px": refined[0][0] - truth_x if refined else None,
                        "anchored_x": anchored["x"] if anchored else None,
                        "anchored_error_px": anchored["x"] - truth_x if anchored else None})
    # No parameter fitting: the late segment is a temporal holdout for this reference,
    # not an independent map/client/session validation.
    split = rows[len(rows) * 2 // 3]["capture_clock"]
    def summarize(group):
        return {"raw": metrics([s["raw_error_px"] for s in group]),
                "refined": metrics([s["refined_error_px"] for s in group
                                    if s["refined_error_px"] is not None]),
                "anchored": metrics([s["anchored_error_px"] for s in group
                                     if s["anchored_error_px"] is not None])}

    return {"schema_version": 1, "input_sent": False, "native_acceptance": False,
            "source_sha256": digest, "reference_sha256": hashlib.sha256(
                reference_path.read_bytes()).hexdigest(),
            "decisions_sha256": hashlib.sha256(decisions).hexdigest(),
            "annotations_sha256": hashlib.sha256(annotations.read_bytes()).hexdigest(),
            "evaluation_recording": str(recording), "reference_recording": str(basis),
            "production_anchor": anchor.record["name"] if anchor else None,
            "validation_landmarks": [item[0]["name"] for item in templates],
            "training_evaluation_overlap_frames": 0 if anchor else None,
            "scope": "Horizontal consistency of name-tag feet against independent ladder/rope X",
            "annotation_uncertainty_px": labels["annotation_uncertainty_px"],
            "all": summarize(samples),
            "temporal_holdout": summarize([s for s in samples if s["clock"] >= split]),
            "frames": len(rows), "accepted": len(samples), "refused": refused,
            "samples": samples, "limitations": [
                "No vertical accuracy, contact, grip or native navigation acceptance",
                "Landmark world coordinates and image annotations do not use the minimap transform",
                "Screen centre uses logged detector; true sprite-feet accuracy not certified",
                "Client/map-specific X evidence; no other-map or other-resolution acceptance",
                "Annotations and matching have pixel uncertainty; no control model is fitted"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-recording", type=Path)
    parser.add_argument("--scene-anchor", action="store_true")
    args = parser.parse_args()
    protected = (Path(__file__).resolve().parents[1] / "data").resolve()
    target = args.output.resolve()
    if target.is_relative_to(protected) or target.is_relative_to(args.recording.resolve()):
        parser.error("Output must stay outside saved data and recording")
    report = validate(args.recording, args.annotations, args.source,
                      reference_recording=args.reference_recording, scene_anchor=args.scene_anchor)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    print(json.dumps({k: report[k] for k in ("frames", "accepted", "all", "temporal_holdout")}))


if __name__ == "__main__":
    main()
