"""Movement links computed from an imported map's geometry. Pure; no capture or input.

Each move names its launch and landing feet and a short trace the navigator must stay
near. Moves are proposals: navigation decides which ones may be used and proves them.
"""

from dataclasses import dataclass

from .public_map import height, span

JUMP_RISE_PX = 75  # highest jump-up; the game's jump peaks near 77 px, recordings reached 67
JUMP_GAP_PX = 96  # widest gap crossed by a level or upward jump; recordings crossed 96 px
FALL_GAP_PX = 150  # a jump off an edge reaches farther while it falls
WALK_GAP_PX = 32  # same-height neighbours closer than this are walked across
LEVEL_PX = 24  # surfaces this close in height count as level (the navigator's tolerance)
CLIMB_PX = 30  # feet move this far along a rope to confirm a grab or a climb-off
INSET_PX = 16  # launch and landing stay this far inside a platform's end
SIMPLER = {"walk": 0, "climb": 1, "drop": 2, "jump": 3}


@dataclass(frozen=True)
class Move:
    id: str
    source: str
    target: str
    kind: str
    trace: tuple[tuple[float, float], ...]

    @property
    def link(self) -> dict:
        return {"id": self.id, "from": self.source, "to": self.target, "kind": self.kind}


def _inside(item: dict, x: float) -> float:
    left, right = span(item)
    return min(max(x, left + INSET_PX), right - INSET_PX) if right - left > 2 * INSET_PX \
        else (left + right) / 2


def _below(platforms: list[dict], x: float, y: float) -> dict | None:
    """The first platform under (x, y): the one a fall from there lands on."""
    under = [p for p in platforms if span(p)[0] <= x <= span(p)[1] and height(p, x) > y + 1]
    return min(under, key=lambda p: height(p, x), default=None)


def _point(item: dict, x: float) -> tuple[float, float]:
    return round(x, 1), round(height(item, x), 1)


def generate(profile: dict) -> list[Move]:
    platforms, ropes = profile["platforms"], profile["ropes"]
    moves: dict[tuple[str, str], Move] = {}

    def add(source: str, target: str, kind: str, *trace: tuple[float, float]) -> None:
        # One move per pair; the simplest kind wins (walking beats dropping beats jumping).
        prior = moves.get((source, target))
        if source != target and (prior is None or SIMPLER[kind] < SIMPLER[prior.kind]):
            moves[(source, target)] = Move(f"m_{source}_{target}", source, target, kind,
                                           tuple((round(x, 1), round(y, 1)) for x, y in trace))

    for a in platforms:
        a_left, a_right = span(a)
        for side, edge in ((-1, a_left), (1, a_right)):
            # Off this end: walk across a hairline gap, fall to what lies under the end,
            # or jump to a platform beyond or above it.
            launch = _point(a, edge - side * INSET_PX / 2)
            for b in platforms:
                if b is a:
                    continue
                b_left, b_right = span(b)
                past = edge + side * 2 * INSET_PX
                if b_left <= past <= b_right:  # b runs on under or beside this end
                    gap, landing = 0.0, _point(b, past)
                else:
                    near = b_left if side > 0 else b_right
                    gap = side * (near - edge)
                    if gap < 0:
                        continue
                    landing = _point(b, _inside(b, near + side * INSET_PX))
                rise = launch[1] - landing[1]
                if abs(rise) <= LEVEL_PX and gap <= WALK_GAP_PX:
                    add(a["id"], b["id"], "walk", launch, landing)
                elif -LEVEL_PX < rise <= JUMP_RISE_PX and gap <= JUMP_GAP_PX:
                    peak = min(launch[1], landing[1]) - 40
                    add(a["id"], b["id"], "jump", launch, ((launch[0] + landing[0]) / 2, peak),
                        landing)
                elif (rise <= -LEVEL_PX and gap <= FALL_GAP_PX
                      and _below(platforms, landing[0], launch[1]) is b):
                    add(a["id"], b["id"], "jump", launch, (landing[0], launch[1] - 30), landing)
        for b in platforms:
            if b is a:
                continue
            for side, edge in ((-1, span(b)[0]), (1, span(b)[1])):
                # From beside a higher platform's end, jump in onto it.
                start = edge + side * 2 * INSET_PX
                if a_left <= start <= a_right:
                    launch, landing = _point(a, start), _point(b, edge - side * INSET_PX)
                    if LEVEL_PX < launch[1] - landing[1] <= JUMP_RISE_PX:
                        add(a["id"], b["id"], "jump", launch,
                            ((launch[0] + landing[0]) / 2, landing[1] - 40), landing)
            lo, hi = max(a_left, span(b)[0]), min(a_right, span(b)[1])
            if hi - lo < 2 * INSET_PX:
                continue
            # Where both overlap: walk where they meet in height, drop through to the
            # platform directly below, or jump straight up to the one directly above.
            xs = sorted((lo + INSET_PX + k * 8 for k in range(int((hi - lo - 2 * INSET_PX) / 8)
                                                             + 1)),
                        key=lambda x: abs(x - (lo + hi) / 2))
            meet = min(xs, key=lambda x: abs(height(a, x) - height(b, x)))
            if abs(height(a, meet) - height(b, meet)) <= LEVEL_PX:  # slopes that meet
                add(a["id"], b["id"], "walk", _point(a, meet), _point(b, meet))
                continue
            for x in xs:
                launch, landing = _point(a, x), _point(b, x)
                rise = launch[1] - landing[1]
                if rise < -LEVEL_PX and _below(platforms, x, launch[1]) is b:
                    add(a["id"], b["id"], "drop", launch, landing)
                elif LEVEL_PX < rise <= JUMP_RISE_PX and _below(platforms, x, landing[1]) is a:
                    add(a["id"], b["id"], "jump", launch, (x, landing[1] - 30), landing)
                else:
                    continue
                break

    for rope in ropes:
        x, top, bottom = rope["start"]["x"], rope["start"]["y"], rope["end"]["y"]
        for p in platforms:
            left, right = span(p)
            if left <= x <= right:
                y = height(p, x)
                if bottom - CLIMB_PX <= y <= bottom + LEVEL_PX:  # standing at its foot
                    add(p["id"], rope["id"], "climb", (x, y), (x, y - CLIMB_PX))
                    add(rope["id"], p["id"], "climb", (x, y - CLIMB_PX), (x, y))
                elif bottom < y <= bottom + JUMP_RISE_PX:  # jump up to its foot
                    add(p["id"], rope["id"], "climb", (x, y), (x, bottom - CLIMB_PX / 2))
                elif top - LEVEL_PX <= y <= top + CLIMB_PX:  # stepping off at its top
                    add(rope["id"], p["id"], "climb", (x, y + CLIMB_PX), (x, y))
                    add(p["id"], rope["id"], "climb", (x, y), (x, y + CLIMB_PX))
                continue
            # A platform beside the rope: jump onto the rope, or off it onto the platform.
            # The gap is measured from the rope's center; the body reaches past it.
            edge = right if x > right else left
            if abs(x - edge) > JUMP_GAP_PX + INSET_PX:
                continue
            y = height(p, edge)
            if top - JUMP_RISE_PX <= y < top and abs(x - edge) <= JUMP_GAP_PX + INSET_PX:
                landing = _point(p, _inside(p, edge))  # jump off the rope's top
                add(rope["id"], p["id"], "jump", (x, top + CLIMB_PX / 2),
                    ((x + landing[0]) / 2, y - 40), landing)
            if top <= y <= bottom and abs(x - edge) <= JUMP_GAP_PX:
                landing = _point(p, _inside(p, edge))
                add(p["id"], rope["id"], "climb", landing, (x, y - CLIMB_PX / 2))
                add(rope["id"], p["id"], "jump", (x, y - CLIMB_PX / 2),
                    ((x + landing[0]) / 2, y - 40), landing)
    return list(moves.values())
