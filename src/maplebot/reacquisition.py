"""Bounded player reacquisition for combat and farming. Pure: the runtime owns input."""

from dataclasses import dataclass

# Same bounds as navigation's recognition recovery.
RECOVERY_SECONDS = 2.0
RESUME_MATCHES = 2
RESUME_SPACING = 0.15


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
