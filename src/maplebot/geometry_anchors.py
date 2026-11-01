"""Associate shared image structures with world geometry. No per-map visual resources."""

import math

import numpy as np


def world_features(source):
    result = []
    for index, rope in enumerate(source.get("ladderRopes", ())):
        result.append(("ladder" if rope["isLadder"] else "rope", rope["x"],
                       min(rope["y1"], rope["y2"]), max(rope["y1"], rope["y2"]),
                       f"vertical{index}"))
    for index, portal in enumerate(source.get("portals", ())):
        if portal.get("type") == 2:
            result.append(("portal", portal["x"], portal["y"] - 120, portal["y"],
                           f"portal{index}"))
    # Same-height adjoining physical segments share one horizontal constraint.
    rows = sorted((r["y1"], r["x1"], r["x2"]) for r in source.get("footholds", {}).values()
                  if r["x1"] < r["x2"] and abs(r["y2"] - r["y1"]) <= 2)
    floors = []
    for y, left, right in rows:
        if floors and abs(y - floors[-1][0]) <= 2 and left <= floors[-1][2]:
            floors[-1][2] = max(right, floors[-1][2])
        else:
            floors.append([y, left, right])
    result.extend(("surface", y, left, right, f"floor{i}")
                  for i, (y, left, right) in enumerate(floors) if right - left >= 64)
    return result[:2048]


def cluster(pairs, tolerance):
    groups = []
    for pair in sorted(pairs, key=lambda p: p[0]):
        if groups and pair[0] - groups[-1][0][0] <= tolerance:
            groups[-1].append(pair)
        else:
            groups.append([pair])
    return groups


def independent(pairs):
    center = float(np.median([p[0] for p in pairs]))
    chosen, observed, world = [], set(), set()
    for pair in sorted(pairs, key=lambda p: abs(p[0] - center)):
        if pair[1] not in observed and pair[2] not in world:
            chosen.append(pair)
            observed.add(pair[1])
            world.add(pair[2])
    return chosen


class GeometryAnchors:
    def __init__(self, source):
        self.world = world_features(source)

    def locate(self, features, screen, coarse):
        if (len(screen) != 2 or len(coarse) != 2
                or not all(math.isfinite(v) for v in (*screen, *coarse))):
            return {"state": "uncertain", "xy": None, "reason": "Invalid coarse observation"}
        expected = (screen[0] - coarse[0], screen[1] - coarse[1])
        features = features[:64]
        pairs = {"x": [], "y": []}
        for i, feature in enumerate(features):
            for kind, coordinate, start, end, key in self.world:
                if feature.kind != kind:
                    continue
                axis = "y" if kind == "surface" else "x"
                index = 1 if axis == "y" else 0
                offset = feature.coordinate - coordinate
                if abs(offset - expected[index]) > 32:
                    continue
                other = expected[1 - index]
                overlap = min(feature.end, end + other) - max(feature.start, start + other)
                if overlap < min(48, (feature.end - feature.start) / 2):
                    continue
                pairs[axis].append((offset, i, key, feature.uncertainty))
        x_groups = [independent(g) for g in cluster(pairs["x"][:512], 4)]
        y_groups = [independent(g) for g in cluster(pairs["y"][:512], 4)]
        proposals = []
        for xs in x_groups[:32]:
            for ys in y_groups[:32]:
                combined = xs + ys
                # One observed object cannot vote for multiple world objects, or vice versa.
                if (len({p[1] for p in combined}) != len(combined)
                        or len({p[2] for p in combined}) != len(combined)):
                    continue
                dx = float(np.median([p[0] for p in xs]))
                dy = float(np.median([p[0] for p in ys]))
                proposals.append({"offset": [dx, dy], "support": len(combined),
                                  "uncertainty": [max(p[3] for p in xs), max(p[3] for p in ys)]})
        proposals.sort(key=lambda p: -p["support"])
        if not proposals:
            return {"state": "uncertain", "xy": None,
                    "reason": "Need independent horizontal and vertical scene constraints",
                    "candidates": len(features)}
        best = proposals[0]
        if any(p["support"] == best["support"]
               and max(abs(a - b) for a, b in zip(p["offset"], best["offset"], strict=True)) > 4
               for p in proposals[1:]):
            return {"state": "uncertain", "xy": None, "reason": "Competing geometry matches",
                    "hypotheses": len(proposals)}
        candidate = [screen[i] - best["offset"][i] for i in (0, 1)]
        precise = max(best["uncertainty"]) <= 4
        return {"state": "candidate", "candidate_xy": candidate,
                "xy": candidate if precise else None, "uncertainty_xy": best["uncertainty"],
                "support": best["support"], "hypotheses": len(proposals),
                "reason": "Geometric agreement; collision/true-feet offsets unverified",
                "contact_verified": False}
