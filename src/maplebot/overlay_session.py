"""A shared fail-closed control lease. It never authorizes keyboard output."""

import json
import re
import threading
import time

START_COMMANDS = frozenset({"arm", "dry_run", "probe", "autopotter_live",
                            "nav_start", "nav_go", "nav_edge", "nav_walk"})
AREA_ID = re.compile(r"[a-f0-9]{32}")
CIRCUIT_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
BATCH_OUTPUT_LIMIT = 4000


def batch_request(payload):
    """Validate a dashboard batch request the same way the in-game overlay does."""
    kind, area, minutes = payload.get("kind"), payload.get("area"), payload.get("minutes")
    if kind not in ("learn", "single") or not isinstance(area, str) or not AREA_ID.fullmatch(area):
        raise ValueError("Invalid batch request")
    if type(minutes) is not int or minutes not in (1, 15):
        raise ValueError("Choose a 1 or 15 minute run")
    request = {"kind": kind, "area": area, "minutes": minutes}
    if kind == "learn":
        circuit = payload.get("circuit")
        if (not isinstance(circuit, dict) or not isinstance(circuit.get("id"), str)
                or not CIRCUIT_ID.fullmatch(circuit["id"])
                or type(circuit.get("revision")) is not int
                or circuit["revision"] < 1):
            raise ValueError("Choose a saved loop revision")
        request["circuit"] = {"id": circuit["id"], "revision": circuit["revision"]}
    return request


def batch_report(value):
    """Keep only the in-game overlay's batch fields, bounded, for the dashboard to show."""
    if not isinstance(value, dict):
        return None
    report = {"running": value.get("running") is True}
    if value.get("kind") in ("learn", "single"):
        report["kind"] = value["kind"]
    for key in ("line", "output"):
        if isinstance(value.get(key), str):
            report[key] = value[key][-BATCH_OUTPUT_LIMIT:]
    if type(value.get("code")) is int:
        report["code"] = value["code"]
    return report


DISPLAY_LAYERS = ("enemies", "range", "lines")


def display_settings(value):
    """The dashboard's drawing toggles, or None when the payload carries none or is invalid."""
    if not isinstance(value, dict):
        return None
    if any(type(value.get(name)) is not bool for name in DISPLAY_LAYERS):
        return None
    return {name: value[name] for name in DISPLAY_LAYERS}


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
        self.companions = {}
        # The dashboard's drawing toggles, shown in game too.
        self.display = None
        # One dashboard batch request waits here until the in-game overlay takes it. The host runs
        # it through its own guarded batch launcher; this lease never starts input itself.
        self.batch_pending = None
        self.batch_sequence = 0
        self.batch_state = {"running": False}

    def companion_heartbeat(self, payload):
        """Observe in-game overlay health without granting or extending control ownership."""
        owner = payload.get("owner")
        if not isinstance(owner, str) or not 16 <= len(owner) <= 80:
            raise ValueError("Invalid overlay owner")
        if windows := getattr(self.app, "windows", None):
            windows.verify_overlay(payload.get("hwnd"))
        with self.lock:
            self.companions[owner] = self.clock() + 2
            self._start_watch()
            if (report := batch_report(payload.get("batch"))) is not None:
                self.batch_state = report
            ack = payload.get("batch_ack")
            pending = self.batch_pending
            if isinstance(ack, dict) and pending and ack.get("id") == pending["id"]:
                if ack.get("started") is not True:
                    reason = str(ack.get("reason") or "The in-game overlay refused the batch")[:300]
                    self.batch_state = {"running": False, "output": json.dumps({"blocked": reason})}
                self.batch_pending = None
            ready = self.dashboard_ready()
            return {"connected": True, "controller_ready": ready,
                    "batch_request": self.batch_pending, "display": self.display if ready else None}

    def _companion_live(self):
        return any(deadline is not None and self.clock() < deadline
                   for deadline in self.companions.values())

    def dashboard_batch(self, payload):
        """Queue one batch from the dashboard holding the lease, for the in-game overlay to run."""
        owner = payload.get("owner")
        with self.lock:
            if not (self.dashboard_ready() and owner == self.owner):
                raise ValueError("Dashboard controls are disconnected; reload the dashboard")
            if not self._companion_live():
                raise ValueError("Start the in-game overlay first; batches run through it")
            if self.batch_pending or self.batch_state.get("running"):
                raise ValueError("A batch is already running")
            request = batch_request(payload)
            self.batch_sequence += 1
            self.batch_pending = {**request, "id": self.batch_sequence}
            return {"queued": True, "id": self.batch_sequence}

    def batch_status(self):
        with self.lock:
            return {**self.batch_state, "pending": self.batch_pending is not None}

    def dashboard_ready(self):
        return bool(self.owner and self.surface == "dashboard" and not self.expired
                    and self.clock() < self.deadline)

    def _start_watch(self):
        if self.worker is None:
            self.worker = threading.Thread(target=self._watch, daemon=True,
                                           name="overlay-lease")
            self.worker.start()

    def heartbeat(self, payload):
        if windows := getattr(self.app, "windows", None):
            windows.verify_overlay(payload.get("hwnd"))
        return self._heartbeat(payload, "overlay")

    def dashboard_heartbeat(self, payload):
        # The browser never covers the game with a transparent native window.
        # Its authenticated route retains the same exclusive, expiring lease.
        result = self._heartbeat(payload, "dashboard")
        with self.lock:
            if (display := display_settings(payload.get("display"))) is not None:
                self.display = display
            return result

    def _heartbeat(self, payload, surface):
        owner = payload.get("owner")
        panel = payload.get("panel")
        if not isinstance(owner, str) or not 16 <= len(owner) <= 80 or type(panel) is not bool:
            raise ValueError("Invalid overlay heartbeat")
        with self.lock:
            same_owner = self.owner == owner and self.surface == surface
            live = self.owner is not None and not self.expired and self.clock() < self.deadline
            if live and not same_owner:
                raise ValueError(
                    "Another dashboard tab holds controls; close it"
                    if self.surface == "dashboard"
                    else "Another overlay is connected"
                )
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
            self._start_watch()
        return {"connected": True, "panel": panel, "close_requested": self.close_requested,
                "batch": self.batch_status()}

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
            for owner, deadline in list(self.companions.items()):
                if deadline is not None and self.clock() >= deadline:
                    self.companions[owner] = None
                    self.app.stop_requested.set()
                    self.app.safe_stop("OPERATOR_STOP", "In-game overlay disconnected; bot off")

    def _watch(self):
        while not self.app.closed.wait(0.1):
            self.check()

    def block_reason(self):
        # Watchdog reads must never wait for a lease writer that is releasing keys.
        if self.owner and (self.expired or self.clock() >= self.deadline):
            return f"{self.surface.title()} disconnected; reconnect before starting"
        if self.companions and not self.dashboard_ready():
            return "Connect the browser dashboard before starting"
        # Open settings no longer refuse a start (operator decision, 2026-11-01);
        # opening them still stops running work.
        return None

    def guard(self, name):
        if name in START_COMMANDS and (reason := self.block_reason()):
            raise ValueError(reason)
