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
    class WindowStyle:
        def __call__(self, *args):
            return 0
    windows.api = SimpleNamespace(SetForegroundWindow=lambda hwnd: None,
                                  SetWindowPos=RaiseWindow(), GetWindowLongW=WindowStyle())
    windows._wait_foreground = lambda hwnd: False
    windows._click_caption = lambda hwnd: calls.append(hwnd)
    assert not windows.focus(42, click_fallback=allowed)
    assert calls == ([42] if allowed else [])

@pytest.mark.parametrize("state,bottom,width", [(0x8000,30,600),(0x10000,30,600),
                                               (1,30,600),(0,80,600),(0,30,100)])
def test_caption_geometry_rejects_hidden_client_overlap_and_buttons(state, bottom, width):
    from maplebot.geometry import Rect
    from maplebot.windows import TitleBarInfo, caption_point
    info = TitleBarInfo()
    info.rect.left, info.rect.top, info.rect.right, info.rect.bottom = 25, 7, 25+width, bottom
    info.states[0] = state
    with pytest.raises(RuntimeError, match="title bar"):
        caption_point(info, Rect(3,30,1366,768))


def test_native_caption_point_is_outside_gameplay_and_window_buttons():
    from maplebot.geometry import Rect
    from maplebot.windows import TitleBarInfo, caption_point
    info = TitleBarInfo()
    info.rect.left, info.rect.top, info.rect.right, info.rect.bottom = 25,7,1369,30
    assert caption_point(info, Rect(3,30,1366,768)) == (89,18)


def test_foreground_loss_evidence_reads_owner_without_changing_focus():
    windows = Windows.__new__(Windows)
    def title(hwnd, buffer, length):
        buffer.value = "Maple Overlay"
    def process(hwnd, pointer):
        pointer._obj.value = 123
    windows.api = SimpleNamespace(
        GetWindowTextLengthW=lambda hwnd: 13, GetWindowTextW=title,
        GetWindowThreadProcessId=process,
    )
    evidence = windows.foreground_identity(99)
    assert evidence["hwnd"] == 99
    assert evidence["title"] == "Maple Overlay"
    assert evidence["pid"] == 123
    assert evidence["observed_at"] > 0
    assert windows.foreground_identity(None)["hwnd"] is None
