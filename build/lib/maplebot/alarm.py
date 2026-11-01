"""Non-blocking local-PC incident alarm: one sound per incident, injectable audio boundary."""

import threading
from importlib import resources
from pathlib import Path
from typing import Protocol


class AlarmBackend(Protocol):
    def play(self, path: Path) -> None: ...

    def stop(self) -> None: ...

    def beep(self) -> None: ...


class WinsoundBackend:
    def play(self, path: Path) -> None:
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)

    def stop(self) -> None:
        import winsound

        winsound.PlaySound(None, 0)

    def beep(self) -> None:
        import winsound

        winsound.MessageBeep()


class AlarmManager:
    """Keep one incident alarm latched until acknowledgment; the sound plays once."""

    def __init__(self, backend: AlarmBackend | None = None) -> None:
        self.backend = backend or WinsoundBackend()
        self.lock = threading.RLock()
        self.active = False
        self.incident_id: str | None = None
        self.error: str | None = None
        self._resource_context = None

    def start(self, incident_id: str) -> bool:
        with self.lock:
            if self.active:
                return self.incident_id == incident_id
            self.active, self.incident_id, self.error = True, incident_id, None
            try:
                resource = resources.files("maplebot").joinpath("static/alarm.wav")
                if not resource.is_file():
                    raise FileNotFoundError("Packaged alarm.wav is missing")
                self._resource_context = resources.as_file(resource)
                path = self._resource_context.__enter__()
                self.backend.play(path)
            except Exception as error:
                self.error = str(error)
                try:
                    self.backend.beep()
                except Exception as beep_error:
                    self.error = f"{error}; {beep_error}"
            return True

    def acknowledge(self) -> bool:
        with self.lock:
            if not self.active:
                return False
            self.active = False
            try:
                self.backend.stop()
            except Exception as error:
                self.error = str(error)
            if self._resource_context is not None:
                self._resource_context.__exit__(None, None, None)
                self._resource_context = None
            return True

    def close(self) -> None:
        self.acknowledge()

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "active": self.active,
                "incident_id": self.incident_id,
                "error": self.error,
                "fallback": False,
            }
