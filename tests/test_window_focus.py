from types import SimpleNamespace

import pytest

from maplebot.windows import Windows


@pytest.mark.parametrize("accepted", [True, False])
def test_focus_verifies_foreground_instead_of_trusting_request_return(accepted):
    calls = []
    windows = Windows.__new__(Windows)
    windows.get = lambda hwnd: SimpleNamespace(focused=False)
    windows.api = SimpleNamespace(
        SetForegroundWindow=lambda hwnd: calls.append(hwnd),
        GetForegroundWindow=lambda: 42 if accepted else 7,
    )
    assert windows.focus(42) is accepted
    assert calls == [42]


def test_already_focused_window_needs_no_focus_request():
    windows = Windows.__new__(Windows)
    windows.get = lambda hwnd: SimpleNamespace(focused=True)
    windows.api = SimpleNamespace(GetForegroundWindow=lambda: 42)
    assert windows.focus(42)
