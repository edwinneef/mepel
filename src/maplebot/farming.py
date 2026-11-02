"""Bounded farming session and passive pet-potion monitoring. No keyboard authority."""

import math

CHECKPOINT_STOP = "Farming checkpoint limit reached; full session unproven"


class Farming:
    def __init__(self, settings: dict) -> None:
        if not isinstance(settings, dict):
            raise ValueError("Farming settings must be an object")
        self.single_platform = settings.get("single_platform", False)
        if not isinstance(self.single_platform, bool):
            raise ValueError("farming.single_platform must be boolean")
        self.no_consumables = settings.get("no_consumables", False)
        if not isinstance(self.no_consumables, bool):
            raise ValueError("farming.no_consumables must be boolean")
        self.pet_recovery = settings.get("pet_recovery", True)
        if not isinstance(self.pet_recovery, bool):
            raise ValueError("farming.pet_recovery must be boolean")
        # Supervised opt-in: rotation may try one unproven move to a neighbouring platform.
        self.learn_moves = settings.get("learn_moves", False)
        if not isinstance(self.learn_moves, bool):
            raise ValueError("farming.learn_moves must be boolean")
        if self.learn_moves and self.single_platform:
            raise ValueError("farming.learn_moves needs platform rotation, not single_platform")
        self.settings = {"pet_recovery": self.pet_recovery, "no_consumables": self.no_consumables,
                         "single_platform": self.single_platform,
                         "learn_moves": self.learn_moves}
        checkpoint = settings.get("checkpoint_seconds")
        if checkpoint is not None:
            if type(checkpoint) is not int or not 1 <= checkpoint <= 10:
                raise ValueError("farming.checkpoint_seconds must be an integer between 1 and 10")
            if not self.no_consumables or self.pet_recovery:
                raise ValueError("Farming checkpoints require no consumables and no pet recovery")
            self.settings["checkpoint_seconds"] = checkpoint
        for name, default, lower, upper in (
            ("session_minutes", 15, 1, 120),
            ("hp_threshold", 50, 1, 95),
            ("mp_threshold", 50, 1, 95),
            ("recovery_seconds", 5, 1, 30),
            # Temporary: feed the pet every 10 minutes until feeding follows a hunger reading.
            ("feed_seconds", 600, 1, 3600),
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
        if reason := self.checkpoint_reason(now):
            return reason
        if now - self.started >= self.settings["session_minutes"] * 60:
            return "Farming session limit reached; restart manually"
        if not safe:
            return "Farming HUD evidence unavailable; stopped"
        for resource in ("hp", "mp"):
            reading = readings.get(resource, {})
            value = reading.get("percent")
            confidence = reading.get("confidence", 0)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 <= value <= 100
                    or isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                    or not math.isfinite(confidence) or not .9 <= confidence <= 1):
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

    def checkpoint_reason(self, now: float) -> str | None:
        seconds = self.settings.get("checkpoint_seconds")
        if seconds is not None and self.started is not None and now - self.started >= seconds:
            return CHECKPOINT_STOP
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
