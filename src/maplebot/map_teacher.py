"""Learn a map's platforms, ropes and links from the operator's own play. No input.

Heights come from the minimap marker through the walk calibration, the same source
live localization uses, so a learned platform matches whenever the player stands
on it. Only moves the operator actually made become links, in their direction.
"""

import math
import time
from dataclasses import asdict, dataclass, replace

import numpy as np

from .localization import MinimapTransform
from .minimap_reader import MinimapFix
from .perception import Detection
from .surface_names import stabilize

MAX_GAP_SECONDS = 1.0  # longer gaps break motion runs
LINK_SECONDS = 6.0  # a move between two surfaces, long drops included, must finish in time
SPLIT_PX = 48  # gaps wider than this split one height into separate platforms
PAD_PX = 8  # platform ends extend past the outermost visited feet
ROPE_PX = 12  # climb samples within this x distance share one rope
CLIMB_STEPS = 5  # straight jumps rise for fewer frames than a climb
MIN_WIDTH_PX = 24  # narrower runs are usually a pause on a rope, not a ledge
HOP_PX = 250  # a jump that lands back on the same height bridges at most this far
SLOPE_TAG_PX = 24  # name-tag rise allowed for one walking step on a slope
MAX_SAMPLES = 20_000
FLOOR_PX = 8  # platforms this close to the lowest height are the same floor level
BEND_PX = 8  # keep a bend (sloped end) once the walked height leaves the line by this much
COLUMN_PX = 16  # walked feet are summarized per column of this width before bending


@dataclass(frozen=True)
class _Sample:
    t: float
    kind: str  # "ground", "slope" (one walking step up or down), "climb" or "air"
    dot: tuple[float, float]
    feet: tuple[float, float]


class MapTeacher:
    def __init__(self, transform: MinimapTransform) -> None:
        self.transform = transform
        self.samples: list[_Sample] = []
        self.log: list[dict] = []
        self.last: tuple[float, tuple[float, float], tuple[float, float] | None] | None = None
        self.climb_run = 0
        self.identities: dict = {}

    def checkpoint(self) -> dict:
        return {"transform": asdict(self.transform),
                "samples": [asdict(sample) for sample in self.samples], "log": self.log,
                "identities": self.identities}

    @classmethod
    def restore(cls, value: dict) -> "MapTeacher":
        teacher = cls(MinimapTransform(**value["transform"]))
        samples, log = value["samples"], value["log"]
        if not isinstance(samples, list) or not isinstance(log, list):
            raise ValueError("Invalid teaching samples")
        if len(samples) > MAX_SAMPLES or len(log) > MAX_SAMPLES:
            raise ValueError("Too many teaching samples")
        if not all(isinstance(row, dict) for row in log):
            raise ValueError("Invalid teaching log")
        for item in samples:
            if (not isinstance(item, dict)
                    or item.get("kind") not in {"ground", "slope", "climb", "air"}):
                raise ValueError("Invalid teaching sample kind")
            for key in ("dot", "feet"):
                if (not isinstance(item.get(key), (list, tuple)) or len(item[key]) != 2
                        or not all(type(v) in (int, float) and math.isfinite(v)
                                   for v in item[key])):
                    raise ValueError("Invalid teaching sample coordinates")
            t = item["t"]
            if (type(t) not in (int, float) or not math.isfinite(t)
                    or (teacher.samples and t < teacher.samples[-1].t)):
                raise ValueError("Invalid teaching sample time")
            teacher.samples.append(_Sample(t, item["kind"], tuple(item["dot"]),
                                           tuple(item["feet"])))
        # A restart/resume must never invent a move across the interruption. The check log
        # moves with the samples so each move keeps its own position checks.
        if teacher.samples:
            offset = time.perf_counter() - LINK_SECONDS - 2 - teacher.samples[-1].t
            teacher.samples = [replace(sample, t=sample.t + offset)
                               for sample in teacher.samples]
            log = [{**row, "t": row["t"] + offset}
                   if type(row.get("t")) in (int, float) else row for row in log]
        teacher.log = log
        teacher.identities = value.get("identities", {})
        if not isinstance(teacher.identities, dict):
            raise ValueError("Invalid surface identities")
        return teacher

    def add(self, fix: MinimapFix, player: Detection | None,
            camera_shift: tuple[float, float] | None, now: float) -> None:
        fresh = (player is not None and player.kind == "player" and not player.tracked
                 and math.isfinite(player.confidence) and player.confidence >= 0.90)
        tag = (player.box.center[0], float(player.box.feet)) if fresh and player else None
        if len(self.log) < MAX_SAMPLES:
            self.log.append({"t": now, "dot": list(fix.dot) if fix.dot else None,
                             "tag": list(tag) if tag else None,
                             "shift": list(camera_shift) if camera_shift else None,
                             "reason": fix.reason})
        if fix.dot is None or len(self.samples) >= MAX_SAMPLES:
            self.last, self.climb_run = None, 0
            return
        last, self.last = self.last, (now, fix.dot, tag)
        if last is None or now - last[0] > MAX_GAP_SECONDS:
            self.climb_run = 0
            return
        dx, dy = fix.dot[0] - last[1][0], fix.dot[1] - last[1][1]
        rise = (abs(tag[1] - last[2][1] - camera_shift[1])
                if tag is not None and last[2] is not None and camera_shift is not None
                else None)
        # Without a camera estimate (fast scrolling), a level marker still means standing.
        if abs(dy) <= 0.5 and (rise is None or rise <= 3):
            kind, self.climb_run = "ground", 0
        elif abs(dy) <= 1 and abs(dx) > 0.5 and rise is not None and rise <= SLOPE_TAG_PX:
            kind, self.climb_run = "slope", 0
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

    def geometry(self) -> dict:
        """Platforms, ropes, directed links, a boundary and the route problems found."""
        platforms, members = self._platforms()
        ropes = self._ropes()
        links = self._links(members, ropes)
        points = [s.feet for s in self.samples]
        boundary = None
        if points:
            left = min(x for x, _ in points) - 40
            top = min(y for _, y in points) - 100
            boundary = {"x": round(left, 1), "y": round(top, 1),
                        "width": round(max(x for x, _ in points) + 40 - left, 1),
                        "height": round(max(y for _, y in points) + 40 - top, 1)}
        return stabilize({"platforms": platforms, "ropes": ropes, "links": links,
                          "boundary": boundary, "problems": problems(platforms, ropes, links)},
                         self.identities)

    def _walks(self) -> list[list[_Sample]]:
        """Stretches walked without leaving the ground; slope steps keep a walk going."""
        walks: list[list[_Sample]] = []
        walk: list[_Sample] = []
        landed: _Sample | None = None
        for sample in self.samples:
            standing = sample.kind in ("ground", "slope")
            if (standing and walk and sample.t - walk[-1].t <= MAX_GAP_SECONDS
                    and (sample.kind == "slope" or sample.dot[1] == walk[-1].dot[1])):
                walk.append(sample)
                landed = sample
                continue
            if walk:
                walks.append(walk)
            walk = []
            if sample.kind == "ground":
                if (landed and sample.dot[1] == landed.dot[1]
                        and sample.t - landed.t <= LINK_SECONDS
                        and abs(sample.feet[0] - landed.feet[0]) <= HOP_PX):
                    # A hop along one floor: the ground under it is part of that floor.
                    walks.append([landed, sample])
                walk, landed = [sample], sample
            elif sample.kind == "climb":
                landed = None
        if walk:
            walks.append(walk)
        return walks

    def _platforms(self) -> tuple[list[dict], dict[str, set[tuple[float, float]]]]:
        """Join walks that share ground at one height; fit one straight line per group."""
        groups: list[list[_Sample]] = []
        for walk in self._walks():
            joined = [group for group in groups if _touch(group, walk)]
            merged = [s for group in joined for s in group] + walk
            groups = [group for group in groups if group not in joined] + [merged]
        platforms, members = [], {}
        for group in sorted(groups, key=lambda g: (min(s.feet[1] for s in g),
                                                   min(s.feet[0] for s in g))):
            xs = np.array([s.feet[0] for s in group])
            ys = np.array([s.feet[1] for s in group])
            if xs.max() - xs.min() < MIN_WIDTH_PX:
                continue
            left, right = float(xs.min()) - PAD_PX, float(xs.max()) + PAD_PX
            if np.ptp(ys) == 0:
                y_left = y_right = float(ys[0])
            else:
                slope, offset = np.polyfit(xs, ys, 1)
                y_left, y_right = slope * left + offset, slope * right + offset
            key = f"walk_p{len(platforms) + 1}"
            platform = {"id": key,
                        "start": {"x": round(left, 1), "y": float(round(y_left, 1))},
                        "end": {"x": round(right, 1), "y": float(round(y_right, 1))}}
            points = _bends(xs, ys, left, right)
            if points is not None:
                platform["points"] = points
            platforms.append(platform)
            members[key] = {s.dot for s in group}
        return platforms, members

    def _ropes(self) -> list[dict]:
        ropes: list[dict] = []
        for sample in sorted((s for s in self.samples if s.kind == "climb"),
                             key=lambda s: s.feet[0]):
            rope = ropes[-1] if ropes else None
            if rope and sample.feet[0] - rope["xs"][-1] <= ROPE_PX:
                rope["xs"].append(sample.feet[0])
                rope["ys"].append(sample.feet[1])
            else:
                ropes.append({"xs": [sample.feet[0]], "ys": [sample.feet[1]]})
        return [
            {"id": f"walk_r{index + 1}",
             "start": {"x": round(sum(r["xs"]) / len(r["xs"]), 1), "y": round(min(r["ys"]), 1)},
             "end": {"x": round(sum(r["xs"]) / len(r["xs"]), 1), "y": round(max(r["ys"]), 1)}}
            for index, r in enumerate(item for item in ropes if max(item["ys"]) > min(item["ys"]))
        ]

    def _surface(self, sample: _Sample, members: dict, ropes: list[dict]) -> str | None:
        if sample.kind in ("ground", "slope"):
            for key, dots in members.items():
                if sample.dot in dots:
                    return key
        elif sample.kind == "climb":
            for rope in ropes:
                if (abs(rope["start"]["x"] - sample.feet[0]) <= ROPE_PX
                        and rope["start"]["y"] <= sample.feet[1] <= rope["end"]["y"]):
                    return rope["id"]
        return None

    def _links(self, members: dict, ropes: list[dict]) -> list[dict]:
        heights = {key: sum(dot[1] for dot in dots) / len(dots) for key, dots in members.items()}
        links, seen = [], set()
        previous: tuple[str, float] | None = None
        for sample in self.samples:
            surface = self._surface(sample, members, ropes)
            if surface is None:
                continue
            if previous and previous[0] != surface and sample.t - previous[1] <= LINK_SECONDS:
                a, b = previous[0], surface
                if a.startswith("walk_r") or b.startswith("walk_r"):
                    kind = "climb"
                elif heights[b] < heights[a] - 0.5:
                    kind = "jump"
                elif heights[b] > heights[a] + 0.5:
                    kind = "drop"
                else:
                    kind = "jump"
                if (a, b) not in seen:
                    seen.add((a, b))
                    links.append({"id": f"walk_l{len(links) + 1}", "from": a, "to": b,
                                  "kind": kind})
            previous = (surface, sample.t)
        return links


def _touch(group: list[_Sample], walk: list[_Sample]) -> bool:
    """Two stretches belong to one platform if they stand at one height within SPLIT_PX."""
    heights: dict[float, list[float]] = {}
    for sample in group:
        heights.setdefault(sample.dot[1], []).append(sample.feet[0])
    for sample in walk:
        xs = heights.get(sample.dot[1])
        if xs and min(xs) - SPLIT_PX <= sample.feet[0] <= max(xs) + SPLIT_PX:
            return True
    return False


def _bends(xs: np.ndarray, ys: np.ndarray, left: float, right: float) -> list[dict] | None:
    """The walked surface as a polyline when it bends away from one straight line.

    Trapezoid platforms slope down at their ends; a straight fit leaves feet on those
    slopes far below the line. Minimap heights come in ~15 px steps, so columns are
    summarized by their median and only bends larger than BEND_PX are kept.
    """
    columns = []
    for start in np.arange(xs.min(), xs.max() + COLUMN_PX, COLUMN_PX):
        inside = (xs >= start) & (xs < start + COLUMN_PX)
        if inside.any():
            columns.append((float(np.median(xs[inside])), float(np.median(ys[inside]))))
    line = [(left, columns[0][1]), *columns, (right, columns[-1][1])]

    def simplify(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        (x0, y0), (x1, y1) = points[0], points[-1]
        errors = [abs(y - (y0 + (y1 - y0) * (x - x0) / (x1 - x0))) if x1 != x0 else 0.0
                  for x, y in points[1:-1]]
        if not errors or max(errors) <= BEND_PX:
            return [points[0], points[-1]]
        split = errors.index(max(errors)) + 1
        return simplify(points[:split + 1])[:-1] + simplify(points[split:])

    bent = simplify(line)
    if len(bent) <= 2:
        return None
    return [{"x": round(x, 1), "y": float(round(y, 1))} for x, y in bent]


def surface_y(platform: dict, x: float) -> float:
    """Height of a learned platform at x, following its bends when it has them."""
    points = platform.get("points") or [platform["start"], platform["end"]]
    points = sorted(points, key=lambda p: p["x"])
    if points[0]["x"] == points[-1]["x"]:
        return points[0]["y"]
    return float(np.interp(x, [p["x"] for p in points], [p["y"] for p in points]))


def problems(platforms: list[dict], ropes: list[dict], links: list[dict]) -> dict:
    """Surfaces the floor cannot reach, and surfaces with no way back to it.

    The floor ("home") is the lowest platform; among equally low ones, the widest.
    Learned heights carry sub-pixel noise, so "equally low" allows FLOOR_PX.
    """
    if not platforms:
        return {"home": None, "unreachable": [], "stranded": []}

    def level(item: dict) -> float:
        return (item["start"]["y"] + item["end"]["y"]) / 2

    lowest = max(level(p) for p in platforms)
    home = max((p for p in platforms if lowest - level(p) <= FLOOR_PX),
               key=lambda p: p["end"]["x"] - p["start"]["x"])["id"]
    nodes = [item["id"] for item in (*platforms, *ropes)]
    forward: dict[str, set[str]] = {key: set() for key in nodes}
    backward: dict[str, set[str]] = {key: set() for key in nodes}
    for link in links:
        forward[link["from"]].add(link["to"])
        backward[link["to"]].add(link["from"])

    def reach(edges: dict[str, set[str]]) -> set[str]:
        seen, todo = {home}, [home]
        while todo:
            for key in edges[todo.pop()] - seen:
                seen.add(key)
                todo.append(key)
        return seen

    reached, returns = reach(forward), reach(backward)
    return {"home": home, "unreachable": [key for key in nodes if key not in reached],
            "stranded": [key for key in nodes if key in reached and key not in returns]}
