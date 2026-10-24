"""Non-blocking local-PC incident alarm with an injectable audio boundary."""

import threading
from importlib import resources
from pathlib import Path
from typing import Protocol


class AlarmBackend(Protocol):
    def play_loop(self, path: Path) -> None: ...

    def stop(self) -> None: ...

    def beep(self) -> None: ...


class WinsoundBackend:
    def play_loop(self, path: Path) -> None:
        import winsound

        winsound.PlaySound(
            str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP
        )

    def stop(self) -> None:
        import winsound

        winsound.PlaySound(None, 0)

    def beep(self) -> None:
        import winsound

        winsound.MessageBeep()


class AlarmManager:
    """Keep one incident alarm active until explicit acknowledgment or close."""

    def __init__(self, backend: AlarmBackend | None = None) -> None:
        self.backend = backend or WinsoundBackend()
        self.lock = threading.RLock()
        self.active = False
        self.incident_id: str | None = None
        self.error: str | None = None
        self._closed = threading.Event()
        self._resource_context = None
        self._fallback: threading.Thread | None = None

    def start(self, incident_id: str) -> bool:
        with self.lock:
            if self.active:
                return self.incident_id == incident_id
            self.active, self.incident_id, self.error = True, incident_id, None
            self._closed.clear()
            try:
                resource = resources.files("maplebot").joinpath("static/alarm.wav")
                if not resource.is_file():
                    raise FileNotFoundError("Packaged alarm.wav is missing")
                self._resource_context = resources.as_file(resource)
                path = self._resource_context.__enter__()
                self.backend.play_loop(path)
            except Exception as error:
                self.error = str(error)
                self._fallback = threading.Thread(
                    target=self._beep_until_acknowledged,
                    name="alarm-fallback",
                    daemon=True,
                )
                self._fallback.start()
            return True

    def acknowledge(self) -> bool:
        with self.lock:
            if not self.active:
                return False
            self.active = False
            self._closed.set()
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
        fallback = self._fallback
        if fallback and fallback is not threading.current_thread():
            fallback.join(timeout=1)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "active": self.active,
                "incident_id": self.incident_id,
                "error": self.error,
                "fallback": self._fallback is not None and self._fallback.is_alive(),
            }

    def _beep_until_acknowledged(self) -> None:
        while not self._closed.is_set():
            try:
                self.backend.beep()
            except Exception as error:
                with self.lock:
                    self.error = str(error)
            self._closed.wait(0.25)
