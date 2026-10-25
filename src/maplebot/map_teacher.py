"""Learn a map's platforms, ropes and links from the operator's own play. No input.

Heights come from the minimap marker through the walk calibration, the same source
live localization uses, so a learned platform matches whenever the player stands
on it. Only moves the operator actually made become links, in their direction.
"""

import math
from dataclasses import dataclass, replace

from .localization import MinimapTransform
from .minimap_reader import MinimapFix
from .perception import Detection

MAX_GAP_SECONDS = 1.0  # longer gaps break motion runs and links
LINK_SECONDS = 3.0  # a move between two surfaces must finish within this time
SPLIT_PX = 48  # gaps wider than this split one height into separate platforms
PAD_PX = 8  # platform ends extend past the outermost visited feet
ROPE_PX = 12  # climb samples within this x distance share one rope
CLIMB_STEPS = 5  # straight jumps rise for fewer frames than a climb
MIN_WIDTH_PX = 24  # narrower runs are usually a pause on a rope, not a ledge
HOP_PX = 250  # a jump that lands back on the same height bridges at most this far
MAX_SAMPLES = 20_000


@dataclass(frozen=True)
class _Sample:
    t: float
    kind: str  # "ground", "climb" or "air"
    dot: tuple[float, float]
    feet: tuple[float, float]


class MapTeacher:
    def __init__(self, transform: MinimapTransform) -> None:
        self.transform = transform
        self.samples: list[_Sample] = []
        self.last: tuple[float, tuple[float, float], tuple[float, float] | None] | None = None
        self.climb_run = 0

    def add(self, fix: MinimapFix, player: Detection | None,
            camera_shift: tuple[float, float] | None, now: float) -> None:
        if fix.dot is None or len(self.samples) >= MAX_SAMPLES:
            self.last, self.climb_run = None, 0
            return
        fresh = (player is not None and player.kind == "player" and not player.tracked
                 and math.isfinite(player.confidence) and player.confidence >= 0.90)
        tag = (player.box.center[0], float(player.box.feet)) if fresh and player else None
        last, self.last = self.last, (now, fix.dot, tag)
        if last is None or now - last[0] > MAX_GAP_SECONDS:
            self.climb_run = 0
            return
        dx, dy = fix.dot[0] - last[1][0], fix.dot[1] - last[1][1]
        tag_still = (tag is not None and last[2] is not None and camera_shift is not None
                     and abs(tag[1] - last[2][1] - camera_shift[1]) <= 3)
        if abs(dy) <= 0.5 and tag_still:
            kind, self.climb_run = "ground", 0
        elif abs(dx) <= 0.5 and abs(dy) >= 0.5:
            # A straight jump also moves only vertically; a climb keeps one direction.
            direction = 1 if dy > 0 else -1
            same = self.climb_run * direction > 0
            self.climb_run = self.climb_run + direction if same else direction
            kind = "climb" if abs(self.climb_run) >= CLIMB_STEPS else "air"
            if abs(self.climb_run) == CLIMB_STEPS:
                # The run's first steps were already part of the climb.
                for index in range(len(self.samples) - CLIMB_STEPS + 1, len(self.samples)):
                    self.samples[index] = replace(self.samples[index], kind="climb")
        else:
            kind, self.climb_run = "air", 0
        self.samples.append(_Sample(now, kind, fix.dot, self.transform.to_area(*fix.dot)))

    def summary(self) -> dict:
        geometry = self.geometry()
        return {"samples": len(self.samples),
                **{key: len(geometry[key]) for key in ("platforms", "ropes", "links")}}

    def geometry(self) -> dict:
        """Platforms, ropes, directed links and a boundary around everything visited."""
        platforms = []
        for dot_y, spans in sorted(self._ground_spans().items()):
            y = round(self.transform.to_area(0, dot_y)[1], 1)
            merged: list[list[float]] = []
            for left, right in sorted(spans):
                if merged and left - merged[-1][1] <= SPLIT_PX:
                    merged[-1][1] = max(merged[-1][1], right)
                else:
                    merged.append([left, right])
            for left, right in merged:
                if right - left < MIN_WIDTH_PX:
                    continue
                platforms.append({"id": f"walk_p{len(platforms) + 1}", "dot_y": dot_y,
                                  "start": {"x": round(left - PAD_PX, 1), "y": y},
                                  "end": {"x": round(right + PAD_PX, 1), "y": y}})
        ropes = []
        for sample in sorted((s for s in self.samples if s.kind == "climb"),
                             key=lambda s: s.feet[0]):
            rope = ropes[-1] if ropes else None
            if rope and sample.feet[0] - rope["xs"][-1] <= ROPE_PX:
                rope["xs"].append(sample.feet[0])
                rope["ys"].append(sample.feet[1])
            else:
                ropes.append({"xs": [sample.feet[0]], "ys": [sample.feet[1]]})
        ropes = [
            {"id": f"walk_r{index + 1}",
             "start": {"x": round(sum(r["xs"]) / len(r["xs"]), 1), "y": round(min(r["ys"]), 1)},
             "end": {"x": round(sum(r["xs"]) / len(r["xs"]), 1), "y": round(max(r["ys"]), 1)}}
            for index, r in enumerate(item for item in ropes if max(item["ys"]) > min(item["ys"]))
        ]
        links = self._links(platforms, ropes)
        points = [s.feet for s in self.samples]
        boundary = None
        if points:
            left = min(x for x, _ in points) - 40
            top = min(y for _, y in points) - 100
            boundary = {"x": round(left, 1), "y": round(top, 1),
                        "width": round(max(x for x, _ in points) + 40 - left, 1),
                        "height": round(max(y for _, y in points) + 40 - top, 1)}
        for platform in platforms:
            del platform["dot_y"]
        return {"platforms": platforms, "ropes": ropes, "links": links, "boundary": boundary}

    def _ground_spans(self) -> dict[float, list[tuple[float, float]]]:
        """X spans walked without leaving the ground, grouped by marker height."""
        spans: dict[float, list[tuple[float, float]]] = {}
        run: list[_Sample] = []
        landed: _Sample | None = None  # last ground sample, kept across air samples
        for sample in [*self.samples, None]:
            if (sample is not None and sample.kind == "ground" and not run and landed
                    and sample.dot[1] == landed.dot[1]
                    and sample.t - landed.t <= LINK_SECONDS
                    and abs(sample.feet[0] - landed.feet[0]) <= HOP_PX):
                # A hop along one floor: the ground under it is part of that floor.
                left, right = sorted((landed.feet[0], sample.feet[0]))
                spans.setdefault(sample.dot[1], []).append((left, right))
            if sample is not None and sample.kind == "ground":
                landed = sample
            elif sample is not None and sample.kind == "climb":
                landed = None
            if (sample is not None and sample.kind == "ground" and run
                    and sample.dot[1] == run[-1].dot[1]
                    and sample.t - run[-1].t <= MAX_GAP_SECONDS):
                run.append(sample)
                continue
            if run:
                xs = [item.feet[0] for item in run]
                spans.setdefault(run[0].dot[1], []).append((min(xs), max(xs)))
            run = [sample] if sample is not None and sample.kind == "ground" else []
        return spans

    def _surface(self, sample: _Sample, platforms: list[dict], ropes: list[dict]) -> str | None:
        if sample.kind == "ground":
            for platform in platforms:
                if (platform["dot_y"] == sample.dot[1]
                        and platform["start"]["x"] <= sample.feet[0] <= platform["end"]["x"]):
                    return platform["id"]
        elif sample.kind == "climb":
            for rope in ropes:
                if (abs(rope["start"]["x"] - sample.feet[0]) <= ROPE_PX
                        and rope["start"]["y"] <= sample.feet[1] <= rope["end"]["y"]):
                    return rope["id"]
        return None

    def _links(self, platforms: list[dict], ropes: list[dict]) -> list[dict]:
        heights = {item["id"]: item["start"]["y"] for item in platforms}
        links, seen = [], set()
        previous: tuple[str, float] | None = None
        for sample in self.samples:
            surface = self._surface(sample, platforms, ropes)
            if surface is None:
                continue
            if previous and previous[0] != surface and sample.t - previous[1] <= LINK_SECONDS:
                a, b = previous[0], surface
                if a.startswith("walk_r") or b.startswith("walk_r"):
                    kind = "climb"
                elif heights[b] < heights[a]:
                    kind = "jump"
                elif heights[b] > heights[a]:
                    kind = "drop"
                else:
                    kind = "jump"
                if (a, b) not in seen:
                    seen.add((a, b))
                    links.append({"id": f"walk_l{len(links) + 1}", "from": a, "to": b,
                                  "kind": kind})
            previous = (surface, sample.t)
        return links
