import importlib
import sys
import threading
import time
from pathlib import Path
from queue import PriorityQueue
from types import SimpleNamespace

import pytest

from maplebot import navigation_reload
from maplebot.contracts import CommandContext, CommandGate


@pytest.fixture
def stopped_app(tmp_path, monkeypatch):
    package = sys.modules["maplebot"]
    for name in navigation_reload.BUNDLE:
        full = f"maplebot.{name}"
        importlib.import_module(full)
        monkeypatch.setitem(sys.modules, full, sys.modules[full])
        monkeypatch.setattr(package, name, getattr(package, name))
    controller = SimpleNamespace(
        lock=threading.RLock(), enabled=False, suspended=False, held={}, leases={},
        movement_key=None, active=None, queue=PriorityQueue(), execution_lock=threading.Lock())
    navigation = SimpleNamespace(
        agent=None, ticket=None, lease=None, recovery=None, failed={"failed-edge"},
        failed_map="unchanged-map", pending_proofs=[("area", "map", "edge")])
    return SimpleNamespace(
        stop_lock=threading.RLock(), controller=controller, navigation=navigation,
        mode="capture", active_probe=None, farming=None, rotating=False,
        calibrating=False, area_editing=False, arbiter=SimpleNamespace(in_flight={}),
        live_potion_ticket=None, areas=SimpleNamespace(directory=tmp_path),
        command_epoch=3, position=object(), calibration=object(), probed={"jump"},
        stop_record=object(), alarm=object(), session_id="same-session")


@pytest.mark.parametrize(("owner", "field", "value"), [
    ("app", "mode", "navigation"), ("app", "mode", "navigation_wait"),
    ("app", "mode", "live"), ("app", "mode", "pending_arm"),
    ("app", "active_probe", object()), ("app", "farming", object()),
    ("app", "rotating", True), ("app", "calibrating", True),
    ("app", "area_editing", True), ("app", "live_potion_ticket", 1),
    ("navigation", "agent", SimpleNamespace(active=True)),
    ("navigation", "ticket", 1), ("navigation", "lease", 1),
    ("navigation", "recovery", {}),
    ("controller", "enabled", True), ("controller", "suspended", True),
    ("controller", "held", {"left": 1}), ("controller", "leases", {1: object()}),
    ("controller", "movement_key", "left"), ("controller", "active", object()),
    ("arbiter", "in_flight", {1: "navigation"}),
])
def test_reload_refuses_active_activity_or_input(stopped_app, owner, field, value):
    app = stopped_app
    original = app.navigation
    setattr(app if owner == "app" else getattr(app, owner), field, value)
    with pytest.raises(ValueError, match="Navigation reload requires"):
        navigation_reload.reload_navigation(app)
    assert app.navigation is original and app.command_epoch == 3


@pytest.mark.parametrize("busy", ["queue", "executor"])
def test_reload_refuses_pending_or_executing_input(stopped_app, busy):
    controller = stopped_app.controller
    if busy == "queue":
        controller.queue.put((1, 1, object()))
    else:
        controller.execution_lock.acquire()
    with pytest.raises(ValueError, match="idle input"):
        navigation_reload.reload_navigation(stopped_app)


def test_reload_reads_changed_source_preserves_safety_and_invalidates_preview(
        stopped_app, monkeypatch):
    app = stopped_app
    original = app.navigation
    protected = {name: getattr(app, name) for name in (
        "controller", "position", "calibration", "probed", "stop_record", "alarm", "session_id")}
    read = Path.read_bytes

    def changed_source(path):
        value = read(path)
        return value.replace(b"LAUNCH_PX = 16", b"LAUNCH_PX = 19") \
            if path.name == "navigation_executor.py" else value

    monkeypatch.setattr(Path, "read_bytes", changed_source)
    result = navigation_reload.reload_navigation(app)
    assert result["reloaded"] and not result["input_sent"] and result["requires_preview"]
    assert app.command_epoch == 4 and app.mode == "capture"
    assert all(getattr(app, key) is value for key, value in protected.items())
    assert app.navigation is not original
    assert app.navigation.failed == original.failed
    assert app.navigation.failed_map == original.failed_map
    assert app.navigation.pending_proofs == original.pending_proofs
    assert app.navigation.graph is app.navigation.agent is app.navigation.feedback is None
    assert app.navigation.route is None
    executor = sys.modules["maplebot.navigation_executor"]
    adapter = sys.modules["maplebot.navigation_runtime"]
    short_walk = sys.modules["maplebot.short_walk"]
    assert executor.LAUNCH_PX == 19
    assert adapter.Navigator is executor.Navigator
    assert issubclass(short_walk.ShortWalk, executor.Navigator)
    assert adapter.RouteMap is sys.modules["maplebot.navigation"].RouteMap


@pytest.mark.parametrize("broken", [b"invalid python !", b"raise RuntimeError('broken import')"])
def test_broken_update_retains_previous_bundle_and_app(stopped_app, monkeypatch, broken):
    app = stopped_app
    original = app.navigation
    modules = {name: sys.modules[f"maplebot.{name}"] for name in navigation_reload.BUNDLE}
    read = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path:
                        broken if path.name == "navigation_runtime.py" else read(path))
    with pytest.raises((SyntaxError, RuntimeError)):
        navigation_reload.reload_navigation(app)
    assert app.navigation is original and app.command_epoch == 3
    assert all(sys.modules[f"maplebot.{name}"] is module for name, module in modules.items())
    assert all(getattr(sys.modules["maplebot"], name) is module
               for name, module in modules.items())


def test_versioned_command_reloads_through_runtime_and_expires_old_commands(stopped_app):
    from maplebot.runtime import Application

    app = stopped_app
    app.capture_only = False
    envelope = {"schema_version": 1, "session_id": app.session_id,
                "command_id": "reload-command", "issued_at": time.time(),
                "command_epoch": app.command_epoch, "name": "nav_reload_code", "payload": {}}
    name, payload, context = CommandGate().accept(envelope, {
        "session_id": app.session_id, "command_epoch": app.command_epoch})
    assert Application._command(app, name, {**payload, "_context": context})["reloaded"]
    with pytest.raises(ValueError, match="superseded"):
        Application._command(app, "nav_start", {"_context": context})
    assert Application._command(app, name, {
        "_context": CommandContext(app.command_epoch, time.time())})["reloaded"]
    assert app.command_epoch == 5 and not app.controller.enabled
