"""Stopped-only replacement of the navigation bundle on the engine command thread."""

import hashlib
import importlib.util
import sys
from pathlib import Path

BUNDLE = ("navigation", "navigation_executor", "short_walk", "navigation_runtime")


def reload_navigation(app) -> dict:
    controller = app.controller
    with app.stop_lock, controller.lock:
        previous = app.navigation
        if (app.mode != "capture" or app.active_probe is not None
                or app.farming is not None or app.rotating
                or app.calibrating or app.area_editing
                or previous.agent is not None and previous.agent.active
                or previous.ticket is not None or previous.lease is not None
                or previous.recovery is not None):
            raise ValueError("Navigation reload requires Bot Off with no active activity")
        if (controller.enabled or controller.suspended or controller.held
                or controller.leases or controller.movement_key is not None
                or controller.active is not None or not controller.queue.empty()
                or controller.execution_lock.locked() or app.arbiter.in_flight
                or app.live_potion_ticket is not None):
            raise ValueError("Navigation reload requires released, disabled and idle input")

        root = Path(__file__).resolve().parent
        sources = {name: (root / f"{name}.py").read_bytes() for name in BUNDLE}
        # Compile every source first, bypassing .pyc timestamps for rapid edits.
        compiled = {name: compile(source, str(root / f"{name}.py"), "exec")
                    for name, source in sources.items()}
        package = sys.modules[__package__]
        names = {name: f"{__package__}.{name}" for name in BUNDLE}
        old_modules = {name: sys.modules.get(full) for name, full in names.items()}
        old_attributes = {name: getattr(package, name, None) for name in BUNDLE}
        candidates = {}
        try:
            for name, full in names.items():
                spec = importlib.util.spec_from_file_location(full, root / f"{name}.py")
                module = importlib.util.module_from_spec(spec)
                sys.modules[full] = module
                setattr(package, name, module)
                exec(compiled[name], module.__dict__)
                candidates[name] = module
            replacement = candidates["navigation_runtime"].NavigationRuntime(app)
            replacement.failed = set(previous.failed)
            replacement.failed_map = previous.failed_map
            replacement.pending_proofs = list(previous.pending_proofs)
            revision = {name: hashlib.sha256(source).hexdigest()
                        for name, source in sources.items()}
            replacement.code_revision = revision
            replacement.reason = "Navigation code reloaded; preview a fresh route before starting"
        except BaseException:
            for name, full in names.items():
                if old_modules[name] is None:
                    sys.modules.pop(full, None)
                else:
                    sys.modules[full] = old_modules[name]
                if old_attributes[name] is None:
                    if hasattr(package, name):
                        delattr(package, name)
                else:
                    setattr(package, name, old_attributes[name])
            raise
        app.navigation = replacement
        app.command_epoch += 1  # Queued commands from before the replacement must expire.
        return {"reloaded": True, "code": revision, "mode": app.mode,
                "requires_preview": True, "input_sent": False}
