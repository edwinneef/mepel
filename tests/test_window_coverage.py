"""The game-view coverage check exempts only our capture-excluded overlay window."""
from types import SimpleNamespace

import pytest

from maplebot.geometry import Rect
from maplebot.windows import Windows

GAME, OVERLAY, OTHER = 10, 20, 30


def fake(cover: int | None, excluded: set[int]) -> Windows:
    """Game at (0, 0, 1000, 1000); `cover` sits over the bottom-left sample point only."""
    def affinity(hwnd, ref):
        ref._obj.value = 17 if hwnd in excluded else 0
        return 1

    windows = Windows.__new__(Windows)
    windows.overlay = None
    windows.api = SimpleNamespace(
        WindowFromPoint=lambda point: cover if cover and (point.x, point.y) == (50, 950) else GAME,
        GetAncestor=lambda hwnd, flag: hwnd, IsWindow=lambda hwnd: True,
        GetWindowDisplayAffinity=affinity)
    return windows


@pytest.mark.parametrize("cover, verified, excluded_later, clear", [
    (None, False, {OVERLAY}, True),              # nothing over the game
    (OTHER, False, {OVERLAY}, False),            # another window covers a sample point
    (OVERLAY, True, {OVERLAY}, True),            # our verified, capture-excluded overlay
    (OVERLAY, False, {OVERLAY}, False),          # excluded from capture, but never verified
    (OVERLAY, True, set(), False),               # verified once, exclusion since dropped
    (OTHER, True, {OVERLAY, OTHER}, False),      # a different capture-excluded window
])
def test_only_the_verified_capture_excluded_overlay_may_cover_the_game(
        cover, verified, excluded_later, clear):
    excluded = {OVERLAY}
    windows = fake(cover, excluded)
    if verified:
        windows.verify_overlay(OVERLAY)
    excluded.clear()
    excluded.update(excluded_later)
    assert windows.unobscured(GAME, Rect(0, 0, 1000, 1000)) is clear


def test_overlay_without_capture_exclusion_is_refused_and_not_remembered():
    windows = fake(OVERLAY, set())
    with pytest.raises(ValueError, match="capture exclusion"):
        windows.verify_overlay(OVERLAY)
    assert windows.overlay is None
