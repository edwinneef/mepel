"""Persist observed control confirmations, without persisting input enablement."""

import json
import shutil
import time
from pathlib import Path


class ProbeStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def restore(self, context: dict, signatures: dict) -> set[str]:
        try:
            saved = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return set()
        if (
            not isinstance(saved, dict)
            or saved.get("version") != 1
            or saved.get("context") != context
            or not isinstance(saved.get("confirmed"), dict)
        ):
            return set()
        return {
            action for action, signature in signatures.items()
            if saved["confirmed"].get(action) == signature
        }

    def save(self, context: dict, signatures: dict, confirmed: set[str]) -> None:
        saved = {
            "version": 1,
            "context": context,
            "confirmed": {action: signatures[action] for action in sorted(confirmed)
                          if action in signatures},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(f".{time.time_ns()}.bak"))
        temporary.replace(self.path)
