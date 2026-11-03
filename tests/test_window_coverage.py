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

    def rectangle(hwnd, ref):
        ref._obj.left, ref._obj.top = 0, 0
        ref._obj.right, ref._obj.bottom = 1000, 1000
        return 1

    windows = Windows.__new__(Windows)
    windows.overlay = None
    windows.api = SimpleNamespace(
        WindowFromPoint=lambda point: cover if cover and (point.x, point.y) == (50, 950) else GAME,
        GetAncestor=lambda hwnd, flag: hwnd, IsWindow=lambda hwnd: True,
        GetWindow=lambda hwnd, flag: GAME if hwnd == OVERLAY else None,
        IsWindowVisible=lambda hwnd: True, IsIconic=lambda hwnd: False,
        GetWindowRect=rectangle,
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


@pytest.mark.parametrize("underneath, clear", [(GAME, True), (OTHER, False), (None, False),
                                               (OVERLAY, False)])
def test_overlay_does_not_hide_another_window_or_unknown_stack(underneath, clear):
    windows = fake(OVERLAY, {OVERLAY, OTHER})
    windows.verify_overlay(OVERLAY)
    windows.api.GetWindow = lambda hwnd, flag: underneath if hwnd == OVERLAY else GAME
    assert windows.unobscured(GAME, Rect(0, 0, 1000, 1000)) is clear


def test_unknown_underlying_geometry_refuses():
    windows = fake(OVERLAY, {OVERLAY})
    windows.verify_overlay(OVERLAY)
    windows.api.GetWindowRect = lambda hwnd, ref: 0
    assert not windows.unobscured(GAME, Rect(0, 0, 1000, 1000))


@pytest.mark.parametrize("irrelevant", ["hidden", "minimized", "elsewhere"])
def test_underlying_window_outside_visible_sample_does_not_block(irrelevant):
    windows = fake(OVERLAY, {OVERLAY})
    windows.verify_overlay(OVERLAY)
    windows.api.GetWindow = lambda hwnd, flag: OTHER if hwnd == OVERLAY else GAME
    windows.api.IsWindowVisible = lambda hwnd: hwnd != OTHER or irrelevant != "hidden"
    windows.api.IsIconic = lambda hwnd: hwnd == OTHER and irrelevant == "minimized"
    original = windows.api.GetWindowRect

    def rectangle(hwnd, ref):
        original(hwnd, ref)
        if hwnd == OTHER and irrelevant == "elsewhere":
            ref._obj.bottom = 100
        return 1

    windows.api.GetWindowRect = rectangle
    assert windows.unobscured(GAME, Rect(0, 0, 1000, 1000))
