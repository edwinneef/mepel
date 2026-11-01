"""Classic operating bands, separate from published animation hitbox extents."""

import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

TARGETING_SOURCE = "https://meowdb.com/msclassic/formulas/targeting"
WEAPON_SOURCE = "https://meowdb.com/msclassic/guides/weapon-reach"


@dataclass(frozen=True)
class RangeProfile:
    id: str
    label: str
    minimum_px: int
    maximum_px: int
    basic_reaches_px: tuple[int, ...]
    source: str = WEAPON_SOURCE


# Standing basic animations only; exclude crouch and Final Attack. Melee bands
# stay inside the shortest animation with a 10+ px margin. These centre-distance
# bands assume native scale, not knowledge of an enemy's internal hitbox.
PROFILES = (
    RangeProfile("classic_bow", "Bow / crossbow + Arrow Blow", 120, 250,
                 (300,), TARGETING_SOURCE),
    RangeProfile("classic_1h_sword", "1H sword · standard", 0, 60, (88, 73, 102, 84, 83)),
    RangeProfile("classic_1h_sword_short", "1H sword · Long Sword / Gladius group", 0, 50,
                 (85, 64, 78, 74, 70)),
    RangeProfile("classic_1h_axe", "1H axe", 0, 60, (88, 73, 102, 84, 83)),
    RangeProfile("classic_1h_blunt", "1H blunt weapon", 0, 55, (77, 69, 94, 82, 82)),
    RangeProfile("classic_2h_sword", "2H sword · standard", 0, 65, (86, 75, 78, 98, 98)),
    RangeProfile("classic_2h_sword_long", "2H sword · Scimitar / long group", 0, 75,
                 (100, 86, 87, 110, 127)),
    RangeProfile("classic_2h_axe", "2H axe", 0, 70, (99, 84, 85, 90, 90)),
    RangeProfile("classic_2h_blunt", "2H blunt weapon", 0, 70, (99, 84, 85, 90, 90)),
    RangeProfile("classic_spear", "Spear", 0, 100, (133, 120, 116, 130, 111)),
    RangeProfile("classic_polearm", "Polearm", 0, 100, (133, 120, 116, 130, 111)),
)


def range_profile(name: str) -> RangeProfile | None:
    if name == "custom":
        return None
    for profile in PROFILES:
        if profile.id == name:
            return profile
    raise ValueError("Unknown attack range profile; select a listed Classic weapon or custom")


def range_options() -> list[dict]:
    return [asdict(profile) for profile in PROFILES]


class RangeStore:
    """Persist an explicit weapon choice, never input enablement or confirmations."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, default: str) -> str:
        if not self.path.exists():
            return default
        saved = json.loads(self.path.read_text("utf-8"))
        if not isinstance(saved, dict) or saved.get("version") != 1:
            raise ValueError(
                "Invalid combat range settings; preserve the file and restore its backup"
            )
        name = saved.get("profile")
        range_profile(name)
        return name

    def save(self, name: str) -> None:
        range_profile(name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "profile": name}, indent=2), "utf-8")
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(f".{time.time_ns()}.bak"))
        temporary.replace(self.path)
