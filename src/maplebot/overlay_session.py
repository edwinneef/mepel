"""A fail-closed lease for the native overlay. It never authorizes keyboard output."""

import threading
import time

START_COMMANDS = frozenset({"arm", "dry_run", "probe", "autopotter_live",
                            "nav_start", "nav_go", "nav_edge"})


class OverlaySession:
    def __init__(self, app, *, clock=time.monotonic):
        self.app = app
        self.clock = clock
        self.lock = threading.RLock()
        self.owner = None
        self.deadline = 0.0
        self.panel = True
        self.expired = False
        self.worker = None
        self.close_requested = False

    def heartbeat(self, payload):
        owner = payload.get("owner")
        panel = payload.get("panel")
        if not isinstance(owner, str) or not 16 <= len(owner) <= 80 or type(panel) is not bool:
            raise ValueError("Invalid overlay heartbeat")
        if windows := getattr(self.app, "windows", None):
            windows.verify_overlay(payload.get("hwnd"))
        with self.lock:
            if self.owner not in (None, owner) and self.clock() < self.deadline:
                raise ValueError("Another overlay is connected")
            if self.owner != owner or self.expired:
                self.close_requested = False
            if not panel:
                self.close_requested = False
            opening = panel and (not self.panel or self.owner is None or self.expired)
            replacing = self.owner != owner or self.expired
            self.owner, self.panel = owner, panel
            self.deadline, self.expired = self.clock() + 2, False
            if opening or replacing:
                self.pause()
            if self.worker is None:
                self.worker = threading.Thread(target=self._watch, daemon=True,
                                               name="overlay-lease")
                self.worker.start()
        return {"connected": True, "panel": panel, "close_requested": self.close_requested}

    def request_close(self):
        """Ask the owning overlay to close; only its heartbeat can clear the gate."""
        with self.lock:
            if not self.owner or self.expired or self.clock() >= self.deadline:
                raise ValueError("Overlay disconnected; reconnect before closing settings")
            self.close_requested = self.panel
            return {"requested": self.close_requested}


    def pause(self):
        # A completed manual probe has no input left to execute. Retain only that
        # result so the operator can confirm it in settings; all other work stops.
        self.app.stop_requested.set()
        self.app.safe_stop("OPERATOR_STOP", "Overlay settings opened; bot off",
                           preserve_completed_probe=True)

    def check(self):
        with self.lock:
            if self.owner and not self.expired and self.clock() >= self.deadline:
                self.expired = True
                self.app.stop_requested.set()
                self.app.safe_stop("OPERATOR_STOP", "Overlay disconnected; bot off")

    def _watch(self):
        while not self.app.closed.wait(0.1):
            self.check()

    def block_reason(self):
        # Watchdog reads must never wait for a lease writer that is releasing keys.
        if self.owner and (self.expired or self.clock() >= self.deadline):
            return "Overlay disconnected; reconnect before starting"
        if self.owner and self.panel:
            return "Close overlay settings before starting"
        return None

    def guard(self, name):
        if name in START_COMMANDS and (reason := self.block_reason()):
            raise ValueError(reason)
