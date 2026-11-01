"""Map-pinned visual X anchors. Unsupported/ambiguous scenes remain uncertain."""

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np


class SceneAnchor:
    def __init__(self, record, template):
        self.record, self.template = record, template
        if (record.get("version") != 1 or not math.isfinite(record["world_x"])
                or not 0 <= record["local_x"] < template.shape[1]
                or not 2 <= record["uncertainty_px"] <= 32):
            raise ValueError("Invalid scene anchor geometry or uncertainty")
        bounds = record["foreground_hsv"]
        self.mask = cv2.inRange(cv2.cvtColor(template, cv2.COLOR_BGR2HSV),
                                tuple(bounds[0]), tuple(bounds[1]))
        if np.count_nonzero(self.mask) < 100:
            raise ValueError("Scene anchor has too few foreground pixels")

    @classmethod
    def load(cls, public):
        root = Path(__file__).parent / "static" / "landmarks"
        manifest = root / f"{public['id']}.json"
        if not manifest.exists():
            return None
        record = json.loads(manifest.read_text("utf-8"))
        if (record["source_sha256"] != public["sha256"]
                or record["provider"] != public.get("provider", "dreamms")):
            return None
        path = root / record["image"]
        if path.parent != root:
            raise ValueError("Invalid scene anchor path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["template_sha256"]:
            raise ValueError("Scene anchor template changed")
        template = cv2.imread(str(path))
        if template is None:
            raise ValueError("Missing scene anchor template")
        return cls(record, template)

    def locate_x(self, image, screen_x, coarse_x):
        if (not math.isfinite(screen_x) or not math.isfinite(coarse_x)
                or image.shape[1] != self.record["capture_width"]
                or image.shape[0] != self.record["capture_height"]):
            return None
        h, w = self.template.shape[:2]
        expected = screen_x - coarse_x + self.record["world_x"] - self.record["local_x"]
        # Coarse minimap evidence selects a search region only. The returned position
        # comes entirely from the scene landmark, never by smoothing toward the marker.
        left, right = max(0, int(expected) - 48), min(image.shape[1], int(expected) + w + 49)
        if right <= left:
            return None
        region = image[:, left:right]
        if region.shape[0] < h or region.shape[1] < w:
            return None
        scores = cv2.matchTemplate(region, self.template, cv2.TM_CCOEFF_NORMED, mask=self.mask)
        scores = np.clip(np.nan_to_num(scores, nan=-1, posinf=-1, neginf=-1), -1, 1)
        _, best, _, (x, y) = cv2.minMaxLoc(scores)
        scores[max(0, y - h // 2):y + h // 2 + 1,
               max(0, x - w // 2):x + w // 2 + 1] = -1
        if best < .95 or best - float(scores.max()) < .05:
            return None
        camera_x = left + x + self.record["local_x"] - self.record["world_x"]
        position_x = screen_x - camera_x
        if abs(position_x - coarse_x) > 32:
            return None
        return {"x": float(position_x), "uncertainty_px": self.record["uncertainty_px"],
                "score": float(best), "source": "scene_landmark",
                "landmark": self.record["name"], "vertical_verified": False}
