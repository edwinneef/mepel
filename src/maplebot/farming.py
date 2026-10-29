"""Bounded farming session and passive pet-potion monitoring. No keyboard authority."""

import math


class Farming:
    def __init__(self, settings: dict) -> None:
        if not isinstance(settings, dict):
            raise ValueError("Farming settings must be an object")
        self.no_consumables = settings.get("no_consumables", False)
        if not isinstance(self.no_consumables, bool):
            raise ValueError("farming.no_consumables must be boolean")
        self.pet_recovery = settings.get("pet_recovery", True)
        if not isinstance(self.pet_recovery, bool):
            raise ValueError("farming.pet_recovery must be boolean")
        self.settings = {"pet_recovery": self.pet_recovery, "no_consumables": self.no_consumables}
        for name, default, lower, upper in (
            ("session_minutes", 15, 1, 120),
            ("hp_threshold", 50, 1, 95),
            ("mp_threshold", 50, 1, 95),
            ("recovery_seconds", 5, 1, 30),
            ("feed_seconds", None, 1, 3600),
        ):
            value = settings.get(name, default)
            if name == "feed_seconds" and value is None:
                self.settings[name] = None
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not lower <= value <= upper):
                raise ValueError(f"farming.{name} must be between {lower} and {upper}")
            self.settings[name] = value
        self.started: float | None = None
        self.next_feed: float | None = None
        self.low_since: dict[str, float] = {}
        self.feed_ticket: int | None = None

    def start(self, now: float) -> None:
        self.started = now
        interval = None if self.no_consumables else self.settings["feed_seconds"]
        self.next_feed = now + interval if interval is not None else None
        self.last_progress = now
        self.low_since.clear()

    def check(self, now: float, readings: dict, safe: bool) -> str | None:
        if self.started is None:
            return None
        if now - self.started >= self.settings["session_minutes"] * 60:
            return "Farming session limit reached; restart manually"
        if not safe:
            return "Farming HUD evidence unavailable; stopped"
        for resource in ("hp", "mp"):
            reading = readings.get(resource, {})
            value = reading.get("percent")
            if (value is None or not math.isfinite(value)
                    or reading.get("confidence", 0) < .9):
                return f"Farming {resource.upper()} unreadable; stopped"
            if resource == "hp" and value == 0:
                return "HP empty: possible death; restart manually"
            if value <= self.settings[f"{resource}_threshold"]:
                if self.no_consumables:
                    return f"{resource.upper()} low; no consumables available, stopped"
                since = self.low_since.setdefault(resource, now)
                if now - since >= self.settings["recovery_seconds"]:
                    return f"{resource.upper()} recovery failed; check pet and potions"
            else:
                self.low_since.pop(resource, None)
        return None

    def progress(self, now: float, *, active: bool) -> str | None:
        """Bound silent combat waits by elapsed time, independent of capture FPS."""
        if self.started is None:
            return None
        if active:
            self.last_progress = now
        if now - self.last_progress >= 15:
            return "Farming made no combat progress for 15 seconds; inspect saved clip"
        return None

    def snapshot(self) -> dict:
        return {"settings": self.settings, "started": self.started,
                "next_feed": self.next_feed, "feed_ticket": self.feed_ticket}
