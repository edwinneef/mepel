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

@pytest.mark.parametrize("allowed", [True, False])
def test_click_fallback_is_opt_in_and_attempted_only_once(allowed):
    windows = Windows.__new__(Windows)
    windows.get = lambda hwnd: SimpleNamespace(focused=False)
    calls = []
    class RaiseWindow:
        def __call__(self, *args):
            return True
    windows.api = SimpleNamespace(SetForegroundWindow=lambda hwnd: None,
                                  SetWindowPos=RaiseWindow())
    windows._wait_foreground = lambda hwnd: False
    windows._click_caption = lambda hwnd: calls.append(hwnd)
    assert not windows.focus(42, click_fallback=allowed)
    assert calls == ([42] if allowed else [])
