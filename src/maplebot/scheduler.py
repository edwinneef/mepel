"""One arbiter for gameplay keys: HP, then MP, then combat. Pure; no capture or I/O.

Stops do not pass through here: KeyboardController.stop cancels every queued plan and
releases keys immediately. A potion is queued ahead of combat but never cuts the active
plan, so it waits at most one bounded action. Combat waits while a potion is in flight.
"""

from dataclasses import dataclass

from .decision import Action
from .keyboard import PRIORITY_COMBAT, PRIORITY_HP, PRIORITY_MP

SUSTAIN = {"hp": PRIORITY_HP, "mp": PRIORITY_MP}


@dataclass(frozen=True)
class Choice:
    lane: str | None
    action: Action | None
    priority: int
    reason: str


class Arbiter:
    def __init__(self, potion_seconds: float) -> None:
        self.potion_seconds = potion_seconds
        self.in_flight: dict[int, str] = {}

    def choose(self, *, sustain: str | None, combat: Action | None,
               navigation: Action | None = None) -> Choice:
        """At most one key plan per frame; `sustain` is a monitor suggestion, "hp" or "mp"."""
        if sustain is not None:
            if sustain not in SUSTAIN:
                raise ValueError(f"Unknown sustain resource: {sustain}")
            return Choice(sustain, Action(f"{sustain}_potion", self.potion_seconds),
                          SUSTAIN[sustain], f"{sustain.upper()} potion precedes combat")
        if navigation is not None:
            if combat is not None and combat.kind != "release":
                return Choice(None, None, PRIORITY_COMBAT, "Navigation and combat are exclusive")
            if any(lane in SUSTAIN for lane in self.in_flight.values()):
                return Choice(None, None, PRIORITY_COMBAT, "Navigation waits for potion completion")
            return Choice("navigation", navigation, PRIORITY_COMBAT, "Navigation movement")
        if combat is None or combat.kind == "release":
            return Choice(None, combat, PRIORITY_COMBAT, "No combat key")
        if any(lane in SUSTAIN for lane in self.in_flight.values()):
            return Choice(None, None, PRIORITY_COMBAT, "Combat waits for the potion key")
        return Choice("combat", combat, PRIORITY_COMBAT, "Combat key")

    def submitted(self, ticket: int, lane: str) -> None:
        self.in_flight[ticket] = lane

    def finished(self, ticket: int) -> str | None:
        return self.in_flight.pop(ticket, None)

    def reset(self) -> None:
        self.in_flight.clear()
