"""Reproducible generated pixels, NOT a MapleUnity gameplay benchmark."""

import json
from pathlib import Path

import cv2
import numpy as np

from maplebot.config import Config
from maplebot.replay import run_replay


def main() -> None:
    root = Path("artifacts/synthetic")
    frames, templates = root / "frames", root / "templates"
    frames.mkdir(parents=True, exist_ok=True)
    random = np.random.default_rng(771)
    background = random.integers(25, 65, (768, 1024, 3), dtype=np.uint8)
    sprites = {}
    for kind in ("player", "monster"):
        sprites[kind] = random.integers(0, 255, (28, 24, 3), dtype=np.uint8)
        directory = templates / kind
        directory.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(directory / "generated.png"), sprites[kind])
    labels = {}
    for index in range(60):
        camera = index * 2
        image = np.roll(background, -camera, axis=1)
        player_x = 100 + min(index, 48) * 14 - camera
        monster_x = 800 - camera
        image[580:608, player_x : player_x + 24] = sprites["player"]
        image[380:408, 400 - camera : 424 - camera] = sprites["monster"]
        monsters = [[400 - camera, 380, 24, 28]]
        if index < 54:
            image[580:608, monster_x : monster_x + 24] = sprites["monster"]
            monsters.append([monster_x, 580, 24, 28])
        name = f"{index:04d}.png"
        cv2.imwrite(str(frames / name), image)
        labels[name] = {"player": [[player_x, 580, 24, 28]], "monster": monsters}
    label_path = root / "labels.json"
    label_path.write_text(json.dumps(labels), encoding="utf-8")
    result = run_replay(frames, templates, root / "results", Config(), label_path, True)
    result["dataset"] = "60 generated 1024x768 frames; exact synthetic templates, not gameplay"
    (root / "results" / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
