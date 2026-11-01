"""First-frame map observation from public geometry and current pixels only."""

from collections import Counter

from .geometry import Rect
from .geometry_anchors import GeometryAnchors
from .localization import MinimapTracker, MinimapTransform, Platform
from .map_alignment import align
from .minimap_reader import MinimapFix, describe
from .perception import Detection
from .public_map import chains
from .structure_detection import detect


class FirstVisitLocator:
    def __init__(self, source):
        self.source = source
        self.model = GeometryAnchors(source)
        self.ground = self.ground_basis = None
        self.platforms = []
        for chain in chains(source) if "footholds" in source else []:
            points = chain["points"]
            self.platforms.append(Platform(chain["id"], points[0]["x"], points[-1]["x"],
                                           points[0]["y"], points[-1]["y"],
                                           tuple((p["x"], p["y"]) for p in points)))

    def locate(self, image, player, *, now=None, camera=None, identity=None):
        actors = [player["box"]] if player else []
        features = detect(image, actors)
        output = {"xy": None, "state": "uncertain", "precision_verified": False,
                  "structures": dict(Counter(f.kind for f in features)), "input_sent": False}
        minimap = describe(image)
        if not minimap or not minimap["dot"]:
            return {**output, "reason": "No unique automatically located minimap marker"}
        automatic = align(image, minimap["canvas"], self.source["miniMap"])
        if not player or player.get("tracked") or player.get("confidence", 0) < .90:
            return {**output, "reason": "No fresh player detection"}
        transform, dot = automatic["transform"], minimap["dot"]
        coarse = [transform[f"scale_{axis}"] * dot[axis] + transform[f"offset_{axis}"]
                  for axis in ("x", "y")]
        box = player["box"]
        screen = (box["x"] + box["width"] / 2, box["y"] + box["height"])
        geometry = self.model.locate(features, screen, coarse)
        basis = (identity, image.shape, tuple(sorted(transform.items())))
        if basis != self.ground_basis:
            self.ground = MinimapTracker(MinimapTransform(**transform), tuple(self.platforms))
            self.ground_basis = basis
        grounded = None
        if now is not None and camera is not None:
            fix = MinimapFix((dot["x"], dot["y"]), Rect(**minimap["canvas"]), 1, 1, "Map matched")
            detection = Detection("player", Rect(**box), player["confidence"])
            grounded = self.ground.update(fix, detection, camera, now)
        # Map footholds supply physical Y only after the existing fused stable-surface
        # observation. A grass/stone drawing edge is never used as collision truth.
        x = geometry.get("candidate_x")
        if grounded and grounded.kind == "platform" and x is not None:
            platform = next(p for p in self.platforms if p.id == grounded.surface_id)
            if platform.left <= x <= platform.right:
                geometry = {**geometry, "candidate_xy": [x, platform.y_at(x)],
                            "uncertainty_xy": [geometry["uncertainty_x"], 12],
                            "reason": "Scene X and stable mapped surface; contact unverified",
                            "xy": None, "contact_verified": False}
        # Expose estimates for offline scoring, never runtime input authority.
        return {**output, "geometry": geometry, "coarse_xy": coarse,
                "xy": geometry.get("xy"), "reason": geometry["reason"],
                "candidate_xy": geometry.get("candidate_xy")}
