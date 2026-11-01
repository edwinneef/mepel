"""Bounded player reacquisition for combat and farming. Pure: the runtime owns input."""

import math
from dataclasses import dataclass

from .geometry import Rect

# Same bounds as navigation's recognition recovery. Input stays released throughout; this
# only bounds how long a brief occlusion may pause before control is handed back.
RECOVERY_SECONDS = 4.0
RESUME_MATCHES = 2
# Continuity allowance: base distance plus the furthest a player plausibly moves per second.
CHAIN_RADIUS, CHAIN_SPEED = 24, 160
RESUME_SPACING = 0.15


class ConfirmedSprites:
    """The confirmed name carried by one continuous player track.

    A name tag starts or renews the chain. Each later player frame continues it only when it
    lies near the previous one, within RECOVERY_SECONDS; sprites seen with another name never do.
    """

    def __init__(self) -> None:
        self.names: dict[str, str | None] = {}
        self.last: tuple[str, Rect, float] | None = None

    def observe(self, identity: str, sprite: str | None, box: Rect, now: float) -> None:
        if sprite is not None:
            if sprite in self.names and self.names[sprite] != identity:
                self.names[sprite] = None  # This appearance cannot distinguish the two names.
            else:
                self.names[sprite] = identity
        self.last = (identity, box, now)

    @staticmethod
    def _near(box: Rect, previous: Rect, elapsed: float, max_distance: float) -> bool:
        reach = min(max_distance, CHAIN_RADIUS + CHAIN_SPEED * elapsed)
        return 0 <= elapsed < RECOVERY_SECONDS and math.dist(box.center, previous.center) <= reach

    def follow(self, box: Rect, now: float, max_distance: float) -> None:
        """Weaker player frames next to the last named position keep its chain alive."""
        if self.last is None or not math.isfinite(now):
            return
        identity, named_box, named_at = self.last
        if self._near(box, named_box, now - named_at, max_distance):
            self.last = (identity, box, now)

    def translate(self, dx: float, dy: float) -> None:
        """Keep the chain on screen coordinates while the camera scrolls."""
        if self.last is not None:
            identity, box, at = self.last
            self.last = (identity, box.translated(round(dx), round(dy)), at)

    def resolve(self, sprite: str, box: Rect, now: float, max_distance: float) -> str | None:
        if self.last is None:
            return None
        identity, named_box, named_at = self.last
        # An unseen pose has no appearance-to-name evidence. Permit a pose change
        # in place, but do not use the movement allowance to identify another body.
        if sprite not in self.names:
            max_distance = min(max_distance, CHAIN_RADIUS)
        # A pose never seen beside the tag (a climb or attack frame) continues the track; a
        # sprite also seen with another name cannot tell the two players apart.
        if (self.names.get(sprite, identity) != identity or not math.isfinite(now)
                or not self._near(box, named_box, now - named_at, max_distance)):
            return None
        # A continuous chain of nearby confirmed sprite frames carries the name, so a
        # hidden name tag does not expire the identity while the same sprite stays in view.
        self.last = (identity, box, now)
        return identity


@dataclass
class Step:
    # "pass": no confirmed identity yet, so the policy decides as before; "ok": fresh frame;
    # "pause": suspend input now; "wait": stay suspended; "resume": fresh agreeing frames;
    # "stop": give up with reason.
    state: str
    reason: str = ""


class Reacquisition:
    """Pause on a frame without fresh identity; resume only on the same player.

    Callers pass the fresh identity of each frame: the player template (name tag without
    ":tag-only") when the player is untracked and confident, else None. Tracked or
    predicted positions never count as fresh.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.identity: str | None = None
        self.started: float | None = None
        self.matches = 0
        self.first: float | None = None

    @property
    def recovering(self) -> bool:
        return self.started is not None

    def step(self, identity: str | None, now: float) -> Step:
        if (identity is not None and self.identity and self.identity.startswith("nametag:")
                and not identity.startswith("nametag:")):
            identity = None  # A sprite the named track did not carry may be another player.
        if self.started is None:
            if identity is None:
                if self.identity is None:
                    return Step("pass")
                self.started, self.matches, self.first = now, 0, None
                return Step("pause", "Recognition paused; keys released; reacquiring the player")
            if (self.identity and self.identity.startswith("nametag:")
                    and identity.startswith("nametag:") and identity != self.identity):
                return Step("stop", "Player identity changed during combat")
            if not self.identity or identity.startswith("nametag:"):
                self.identity = identity
            return Step("ok")
        if now - self.started >= RECOVERY_SECONDS:
            return Step("stop", "Player recognition recovery timed out")
        if identity != self.identity:
            if identity and identity.startswith("nametag:"):
                return Step("stop", "Different player found during recovery")
            self.matches, self.first = 0, None
            return Step("wait", "Recognition paused; keys released; reacquiring the player")
        self.matches += 1
        self.first = now if self.first is None else self.first
        if self.matches < RESUME_MATCHES or now - self.first < RESUME_SPACING:
            return Step("wait", "Recognition paused; same player seen; confirming")
        # Recovery ends only once the caller's resume succeeds; a refused resume retries on
        # the next fresh frame under the same deadline.
        return Step("resume", "Player reacquired from fresh agreeing frames; combat resumed")

    def resumed(self) -> None:
        self.started, self.matches, self.first = None, 0, None
