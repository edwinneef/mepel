import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CaptureConfig:
    fps: float = 12
    window_title: str = "MapleStory"
    data_dir: str = "data"


@dataclass(frozen=True)
class DebuggerConfig:
    port: int = 8765


@dataclass(frozen=True)
class PerceptionConfig:
    confidence: float = 0.90
    player_margin: float = 0.04
    max_candidates: int = 24
    nametag_confidence: float = 0.90
    nametag_partial: float = 0.6
    track_seconds: float = 1.0
    track_max_seconds: float = 5.0


@dataclass(frozen=True)
class AgentConfig:
    platform_tolerance: int = 18
    attack_range: int = 65
    movement_seconds: float = 0.12
    attack_seconds: float = 0.06
    verify_seconds: float = 0.45
    max_attack_attempts: int = 6


@dataclass(frozen=True)
class InputConfig:
    left: str = "left"
    right: str = "right"
    attack: str = "z"
    jump: str = "space"
    max_action_seconds: float = 0.25
    emergency_key: str = "f8"


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
class Config:
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    debugger: DebuggerConfig = field(default_factory=DebuggerConfig)
    perception: PerceptionConfig = field(default_factory=PerceptionConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    input: InputConfig = field(default_factory=InputConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)

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
                    ("timing", TimingConfig),
                    ("recording", RecordingConfig),
                )
            }
        )
        if not 1 <= config.capture.fps <= 60:
            raise ValueError("capture.fps must be between 1 and 60")
        if not config.capture.window_title.strip():
            raise ValueError("capture.window_title must identify the intended game window")
        if not 0.5 <= config.perception.confidence <= 1:
            raise ValueError("perception.confidence must be between 0.5 and 1")
        if not 0.01 <= config.input.max_action_seconds <= 0.5:
            raise ValueError("max_action_seconds must be between 0.01 and 0.5")
        for duration in (config.agent.movement_seconds, config.agent.attack_seconds):
            if not 0 < duration <= config.input.max_action_seconds:
                raise ValueError("Action duration exceeds maximum")
        return config
