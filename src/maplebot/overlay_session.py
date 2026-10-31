"""A shared fail-closed control lease. It never authorizes keyboard output."""

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
        self.surface = "overlay"
        self.deadline = 0.0
        self.panel = True
        self.expired = False
        self.worker = None
        self.close_requested = False

    def heartbeat(self, payload):
        if windows := getattr(self.app, "windows", None):
            windows.verify_overlay(payload.get("hwnd"))
        return self._heartbeat(payload, "overlay")

    def dashboard_heartbeat(self, payload):
        # The browser never covers the game with a transparent native window.
        # Its authenticated route retains the same exclusive, expiring lease.
        return self._heartbeat(payload, "dashboard")

    def _heartbeat(self, payload, surface):
        owner = payload.get("owner")
        panel = payload.get("panel")
        if not isinstance(owner, str) or not 16 <= len(owner) <= 80 or type(panel) is not bool:
            raise ValueError("Invalid overlay heartbeat")
        with self.lock:
            same_owner = self.owner == owner and self.surface == surface
            live = self.owner is not None and not self.expired and self.clock() < self.deadline
            if live and not same_owner:
                raise ValueError("Another overlay is connected")
            replacing = not same_owner or not live
            if replacing:
                self.close_requested = False
            if not panel:
                self.close_requested = False
            opening = panel and (not self.panel or replacing)
            self.owner, self.panel, self.surface = owner, panel, surface
            self.deadline, self.expired = self.clock() + 2, False
            if opening or replacing:
                self.pause()
            if self.worker is None:
                self.worker = threading.Thread(target=self._watch, daemon=True,
                                               name="overlay-lease")
                self.worker.start()
        return {"connected": True, "panel": panel, "close_requested": self.close_requested}

    def dashboard_disconnect(self, payload):
        owner = payload.get("owner")
        if not isinstance(owner, str) or not 16 <= len(owner) <= 80:
            raise ValueError("Invalid dashboard owner")
        with self.lock:
            if self.surface == "dashboard" and self.owner == owner and not self.expired:
                self.expired = True
                self.deadline = 0.0
                self.app.stop_requested.set()
                self.app.safe_stop("OPERATOR_STOP", "Dashboard disconnected; bot off")
                return {"disconnected": True}
        return {"disconnected": False}

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
        self.app.safe_stop("OPERATOR_STOP", f"{self.surface.title()} settings opened; bot off",
                           preserve_completed_probe=True)

    def check(self):
        with self.lock:
            if self.owner and not self.expired and self.clock() >= self.deadline:
                self.expired = True
                self.app.stop_requested.set()
                self.app.safe_stop("OPERATOR_STOP", f"{self.surface.title()} disconnected; bot off")

    def _watch(self):
        while not self.app.closed.wait(0.1):
            self.check()

    def block_reason(self):
        # Watchdog reads must never wait for a lease writer that is releasing keys.
        if self.owner and (self.expired or self.clock() >= self.deadline):
            return f"{self.surface.title()} disconnected; reconnect before starting"
        # Open settings no longer refuse a start (operator decision, 2026-11-01);
        # opening them still stops running work.
        return None

    def guard(self, name):
        if name in START_COMMANDS and (reason := self.block_reason()):
            raise ValueError(reason)
