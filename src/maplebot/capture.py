import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import mss
import numpy as np
from numpy.typing import NDArray

from .geometry import Rect
from .windows import Window, Windows

Image = NDArray[np.uint8]


@dataclass
class Calibration:
    title: str
    client_width: int
    client_height: int
    dpi: int
    crop: Rect
    capture_verified: bool = False
    controls_verified: bool = False

    def valid_for(self, window: Window) -> bool:
        return (
            self.client_width == window.client.width
            and self.client_height == window.client.height
            and self.dpi == window.dpi
            and self.title == window.title
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        if path.exists():
            shutil.copy2(path, path.with_suffix(f".{time.time_ns()}.bak"))
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["crop"] = Rect(**raw["crop"])
        # Live gates must be reverified every session, even for the same layout.
        raw.update(capture_verified=False, controls_verified=False)
        return cls(**raw)


class Capture:
    def __init__(self, windows: Windows) -> None:
        windows.dpi_aware()
        self.windows = windows
        self.screen = mss.MSS()

    def close(self) -> None:
        self.screen.close()

    def grab(self, region: Rect) -> Image:
        desktop = self.screen.monitors[0]
        bounds = Rect(desktop["left"], desktop["top"], desktop["width"], desktop["height"])
        if not bounds.contains(region):
            raise RuntimeError("Capture region is outside the visible desktop")
        shot = self.screen.grab(
            {"left": region.x, "top": region.y, "width": region.width, "height": region.height}
        )
        return np.asarray(shot)[:, :, :3].copy()

    def window(self, hwnd: int, calibration: Calibration | None) -> tuple[Image, Window, Rect]:
        before = self.windows.get(hwnd)
        if calibration and not calibration.valid_for(before):
            raise RuntimeError("Window title, size, or DPI changed; recalibrate the Game view")
        crop = (
            calibration.crop
            if calibration
            else Rect(0, 0, before.client.width, before.client.height)
        )
        if not Rect(0, 0, before.client.width, before.client.height).contains(crop):
            raise RuntimeError("Game-view crop is outside the target window")
        region = crop.translated(before.client.x, before.client.y)
        frame = self.grab(region)
        after = self.windows.get(hwnd)
        if before.client != after.client or before.dpi != after.dpi:
            raise RuntimeError("Window moved during capture; discard frame")
        return frame, after, region
