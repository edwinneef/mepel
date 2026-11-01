"""Render paired offline predictions beside independent labels; never recapture frames."""

import argparse
import html
import json
from pathlib import Path

import cv2
import numpy as np

from maplebot.reacquisition import Reacquisition
from tools.occlusion_evaluation import ROOT, check_hash, digest, workspace_path


def recovery_intents(sequence: dict) -> dict:
    """Replay only the pure recovery policy, without pretending runtime gates accepted it."""
    policy, intents = Reacquisition(), []
    for row in sequence["frames"]:
        player, evaluation = row.get("player") or {}, row["evaluation"]
        identity = None
        if evaluation.get("fresh"):
            identity = player.get("identity") or player.get("template", "").removesuffix(
                ":tag-only") or None
        step = policy.step(identity, row["at"])
        verdict = None
        if step.state == "resume":
            verdict = ("wrong" if evaluation.get("visibility") == "hidden" else
                       "supported" if evaluation["outcome"] == "correct_fresh_identity" else
                       "wrong" if evaluation["outcome"] == "wrong_fresh" else "unknown")
            # Counterfactual: subsequent pure-policy state assumes all other gates accepted.
            policy.resumed()
        intents.append({"at": row["at"], "state": step.state, "resume_label_support": verdict})
        if step.state == "stop":
            break
    resumes = [r for r in intents if r["state"] == "resume"]
    return {"id": sequence["id"], "intents": intents, "resume_requests": len(resumes),
            "wrong_resume_requests": sum(r["resume_label_support"] == "wrong" for r in resumes),
            "unknown_resume_requests": sum(r["resume_label_support"] == "unknown" for r in resumes),
            "native_acceptance": False,
            "limits": "Sampled policy intentions only; no real elapsed recovery claim across "
                      "missing frames. Other runtime gates are not evaluated. Zero requests "
                      "cannot establish safe resume accuracy."}


def render(manifest_path: Path, before: Path, after: Path, output: Path,
           root: Path = ROOT) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in (before, after)]
    expected = digest(manifest_path)
    if any(r.get("manifest_sha256") != expected for r in reports):
        raise ValueError("Paired reports must use the same frozen manifest")
    recovery_source = "src/maplebot/reacquisition.py"
    frozen = manifest.get("source_sha256", {}).get(recovery_source)
    if frozen:
        check_hash(workspace_path(root, recovery_source), frozen)
    # Validate all joins and hashes before creating output, never silently compare wrong frames.
    pairs = []
    for sequence in manifest["sequences"]:
        observed = []
        for report in reports:
            matches = [s for s in report["semantic"]["sequences"] if s["id"] == sequence["id"]]
            if len(matches) != 1:
                raise ValueError("Missing or duplicate sequence")
            rows = matches[0]["frames"]
            if [(r["path"], r["at"]) for r in rows] != [
                    (f["path"], f["at"]) for f in sequence["frames"]]:
                raise ValueError("Frame alignment differs")
            observed.append(rows)
        for index, frame in enumerate(sequence["frames"]):
            source = workspace_path(root, frame["path"])
            check_hash(source, frame["sha256"])
            pairs.append((sequence["id"], frame, observed[0][index], observed[1][index], source))
    output.mkdir(parents=True, exist_ok=False)
    (output / "recovery-intents.json").write_text(json.dumps({
        "source_sha256": frozen,
        "before": [recovery_intents(s) for s in reports[0]["semantic"]["sequences"]],
        "after": [recovery_intents(s) for s in reports[1]["semantic"]["sequences"]],
    }, indent=2) + "\n", encoding="utf-8")
    body = ["<h1>Offline occlusion comparison</h1>",
            "<p>Green: independent label, when available. Orange: detector box; ",
            "confidence is not a calibrated probability. Unknown labels remain unknown. ",
            "Left: before; right: after. These images prove neither input nor runtime resume.</p>"]
    for index, (sequence_id, frame, left, right, source) in enumerate(pairs):
        raw = cv2.imread(str(source))
        if raw is None:
            raise ValueError(f"Unreadable image: {source}")
        panels = []
        for name, row in (("before", left), ("after", right)):
            panel = raw.copy()
            for box, color in ((frame.get("box"), (60, 230, 60)),
                               ((row.get("player") or {}).get("box"), (0, 160, 255))):
                if box:
                    x, y, w, h = (round(v) for v in box)
                    cv2.rectangle(panel, (x, y), (x + w, y + h), color, 2)
            player = row.get("player") or {}
            label = (f"{name}: {row['evaluation']['outcome']} "
                     f"score={player.get('confidence')} tracked={player.get('tracked')}")
            banner = np.zeros((32, panel.shape[1], 3), dtype=np.uint8)
            cv2.putText(banner, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, .6,
                        (255, 255, 255), 1)
            panels.append(np.vstack((banner, panel)))
        filename = f"{index:03}.png"
        if not cv2.imwrite(str(output / filename), np.hstack(panels)):
            raise OSError("Could not save comparison")
        caption = (f"{sequence_id} at {frame['at']}: {frame['visibility']}; "
                   f"identity={frame['identity']}; independent box={frame.get('box')}")
        body.append(f'<figure><figcaption>{html.escape(caption)}</figcaption>'
                    f'<a href="{filename}"><img src="{filename}" loading="lazy"></a></figure>')
    same = reports[0]["semantic"] == reports[1]["semantic"]
    body.insert(1, f"<p>Semantic outputs identical: {same}. Timing is compared separately. "
                '<a href="recovery-intents.json">Pure recovery policy intentions</a>.</p>')
    page = ('<!doctype html><meta charset="utf-8"><title>Occlusion comparison</title>'
            '<style>body{font:16px system-ui;margin:24px}img{width:100%}figure{margin:24px 0}'
            'figcaption{margin-bottom:8px}</style>' + "".join(body))
    (output / "index.html").write_text(page, encoding="utf-8")
    return {"frames": len(pairs), "semantic_equal": same, "index": str(output / "index.html")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.manifest, args.before, args.after, args.output)))


if __name__ == "__main__":
    main()
