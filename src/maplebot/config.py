import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .attack_ranges import range_profile


@dataclass(frozen=True)
class CaptureConfig:
    fps: float = 12
    # Display-only drawing refresh; 0 disables the separate display loop.
    display_fps: float = 30
    window_title: str = "MapleStory"
    data_dir: str = "data"


@dataclass(frozen=True)
class DebuggerConfig:
    port: int = 8765


@dataclass(frozen=True)
class PerceptionConfig:
    spawn_source: str = "legacy-dream"
    spawn_revision: str = ""
    confidence: float = 0.90
    player_margin: float = 0.04
    max_candidates: int = 24
    nametag_confidence: float = 0.90
    nametag_partial: float = 0.6
    track_seconds: float = 1.0
    track_max_seconds: float = 5.0
    roi_width: int = 700
    roi_height: int = 420
    enemy_occlusion_seconds: float = 4.0
    enemy_lost_seconds: float = 0.5

    def __post_init__(self) -> None:
        for name in ("enemy_occlusion_seconds", "enemy_lost_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or not .1 <= value <= 10:
                raise ValueError(f"perception.{name} must be between 0.1 and 10 seconds")


@dataclass(frozen=True)
class AgentConfig:
    platform_tolerance: int = 18
    attack_range: int = 65
    attack_min_range: int = 0
    movement_seconds: float = 0.12
    attack_seconds: float = 0.06
    verify_seconds: float = 0.45
    max_attack_attempts: int = 6
    use_skill: bool = True
    skill_low_mp: float = 20.0
    skill_high_mp: float = 40.0
    range_profile: str = "custom"
    clear_seconds: float = 4.0

    def __post_init__(self) -> None:
        profile = range_profile(self.range_profile)
        if profile is not None:
            object.__setattr__(self, "attack_min_range", profile.minimum_px)
            object.__setattr__(self, "attack_range", profile.maximum_px)
        if (not math.isfinite(self.attack_range) or not math.isfinite(self.attack_min_range)
                or not 0 <= self.attack_min_range < self.attack_range):
            raise ValueError(
                "agent.attack_min_range must be below attack_range, both finite and nonnegative"
            )
        if not (math.isfinite(self.clear_seconds) and 1 <= self.clear_seconds <= 60):
            raise ValueError("agent.clear_seconds must be between 1 and 60")


@dataclass(frozen=True)
class InputConfig:
    left: str = "left"
    right: str = "right"
    attack: str = "z"
    jump: str = "space"
    up: str = "up"
    down: str = "down"
    hp_potion: str = "insert"
    mp_potion: str = "delete"
    pet_food: str = "home"
    skill: str = "a"
    max_action_seconds: float = 0.25
    vertical_lease_seconds: float = 1.0
    vertical_lease_max_seconds: float = 8.0
    emergency_key: str = "f8"

    def __post_init__(self) -> None:
        for name in (
            "left", "right", "attack", "jump", "up", "down", "hp_potion", "mp_potion",
            "pet_food", "skill", "emergency_key",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"input.{name} must be a non-empty key name")
        for name, low, high in (
            ("vertical_lease_seconds", 0.01, 8.0),
            ("vertical_lease_max_seconds", 0.01, 30.0),
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"input.{name} must be between {low} and {high}")
        if self.vertical_lease_max_seconds < self.vertical_lease_seconds:
            raise ValueError(
                "input.vertical_lease_max_seconds must not be below vertical_lease_seconds"
            )


@dataclass(frozen=True)
class ProbeConfig:
    potion_effect_seconds: float = 2.0
    potion_min_gain_percent: float = 1.0
    potion_full_percent: float = 95.0

    def __post_init__(self) -> None:
        for name, low, high in (
            ("potion_effect_seconds", 0.1, 10.0),
            ("potion_min_gain_percent", 0.1, 100.0),
            ("potion_full_percent", 1.0, 100.0),
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"probe.{name} must be between {low} and {high}")


@dataclass(frozen=True)
class TimingConfig:
    enabled: bool = True
    hold_variation: float = 0.20
    min_hold_seconds: float = 0.015
    reaction_min_seconds: float = 0.025
    reaction_max_seconds: float = 0.085
    rest_min_seconds: float = 0.020
    rest_max_seconds: float = 0.065
    key_stagger_seconds: float = 0.012
    offset_variation_seconds: float = 0.006
    seed: int | None = None

    def __post_init__(self) -> None:
        for name, low, high in (
            ("hold_variation", 0, 0.9),
            ("min_hold_seconds", 0.001, 0.25),
            ("reaction_min_seconds", 0, 0.5),
            ("reaction_max_seconds", 0, 0.5),
            ("rest_min_seconds", 0, 0.5),
            ("rest_max_seconds", 0, 0.5),
            ("key_stagger_seconds", 0.001, 0.05),
            ("offset_variation_seconds", 0, 0.03),
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"timing.{name} must be between {low} and {high}")
        if self.reaction_min_seconds > self.reaction_max_seconds:
            raise ValueError("timing reaction minimum exceeds maximum")
        if self.rest_min_seconds > self.rest_max_seconds:
            raise ValueError("timing rest minimum exceeds maximum")


@dataclass(frozen=True)
class RecordingConfig:
    auto: bool = True
    buffer_seconds: float = 10
    keyframe_seconds: float = 1.0
    post_seconds: float = 2.0
    max_queue_frames: int = 240
    max_total_mb: int = 2048
    max_age_days: float = 7

    def __post_init__(self) -> None:
        for name, low, high in (
            ("buffer_seconds", 1, 60),
            ("keyframe_seconds", 0, 60),
            ("post_seconds", 0, 30),
            ("max_queue_frames", 1, 2000),
            ("max_total_mb", 1, 1_000_000),
            ("max_age_days", 0.1, 3650),
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"recording.{name} must be between {low} and {high}")


@dataclass(frozen=True)
class PoseCollectionConfig:
    limit: int = 32
    interval: float = 3.0

    def __post_init__(self) -> None:
        if not isinstance(self.limit, int) or not 1 <= self.limit <= 128:
            raise ValueError("pose_collection.limit must be between 1 and 128")
        if not math.isfinite(self.interval) or not 3 <= self.interval <= 60:
            raise ValueError("pose_collection.interval must be between 3 and 60")


@dataclass(frozen=True)
class Config:
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    debugger: DebuggerConfig = field(default_factory=DebuggerConfig)
    perception: PerceptionConfig = field(default_factory=PerceptionConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    input: InputConfig = field(default_factory=InputConfig)
    probe: ProbeConfig = field(default_factory=ProbeConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    pose_collection: PoseCollectionConfig = field(default_factory=PoseCollectionConfig)

    @classmethod
    def load(cls, path: Path) -> "Config":
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        config = cls(
            **{
                name: kind(**raw.get(name, {}))
                for name, kind in (
                    ("capture", CaptureConfig),
                    ("debugger", DebuggerConfig),
                    ("perception", PerceptionConfig),
                    ("agent", AgentConfig),
                    ("input", InputConfig),
                    ("probe", ProbeConfig),
                    ("timing", TimingConfig),
                    ("recording", RecordingConfig),
                    ("pose_collection", PoseCollectionConfig),
                )
            }
        )
        if not 1 <= config.capture.fps <= 60:
            raise ValueError("capture.fps must be between 1 and 60")
        if not (config.capture.display_fps == 0 or 1 <= config.capture.display_fps <= 60):
            raise ValueError("capture.display_fps must be 0 or between 1 and 60")
        if not config.capture.window_title.strip():
            raise ValueError("capture.window_title must identify the intended game window")
        for size in (config.perception.roi_width, config.perception.roi_height):
            if size != 0 and size < 200:
                raise ValueError("perception.roi_width/roi_height must be 0 (off) or at least 200")
        if not 0.5 <= config.perception.confidence <= 1:
            raise ValueError("perception.confidence must be between 0.5 and 1")
        if not 0.01 <= config.input.max_action_seconds <= 0.5:
            raise ValueError("max_action_seconds must be between 0.01 and 0.5")
        if not 0 <= config.agent.skill_low_mp < config.agent.skill_high_mp <= 100:
            raise ValueError("agent.skill_low_mp must be below agent.skill_high_mp, within 0-100")
        for duration in (config.agent.movement_seconds, config.agent.attack_seconds):
            if not 0 < duration <= config.input.max_action_seconds:
                raise ValueError("Action duration exceeds maximum")
        return config
