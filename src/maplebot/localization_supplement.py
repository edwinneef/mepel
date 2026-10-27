"""Pinned, observation-only coverage; never part of a saved map or movement evidence."""

import hashlib
import json
from pathlib import Path

from .profiles import validate_profile

AREA = "98a20c69939d450fb46e5e9342b83734"
BASE_SHA256 = "9826e92b7d38eb1e370afef812418034fc3b07ff4ac2e55b18878cec58cdc4e8"
PLATFORM = {"id": "draft_middle_ledge", "name": "Middle ledge coverage draft",
            "start": {"x": 584.0, "y": 397.7}, "end": {"x": 676.0, "y": 397.7}}


def matches(directory: Path, profile: dict) -> bool:
    if profile["id"] != AREA or profile["revision"] != 4:
        return False
    try:
        body = (directory / f"{AREA}.json").read_bytes()
        return (hashlib.sha256(body).hexdigest() == BASE_SHA256
                and validate_profile(json.loads(body))[0] == profile)
    except (OSError, ValueError, TypeError):
        return False
