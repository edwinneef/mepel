import pytest

from tools.autonomous_navigation import wait_idle


def test_idle_handoff_waits_ten_seconds_without_focus_actions():
    now = [0.0]
    def sleep(seconds):
        now[0] += seconds
    wait_idle(idle=lambda: now[0], clock=lambda: now[0], sleep=sleep)
    assert now[0] == 10


def test_active_user_causes_bounded_pause():
    now = [0.0]
    def sleep(seconds):
        now[0] += seconds
    with pytest.raises(RuntimeError, match='User remains active'):
        wait_idle(idle=lambda: 0, clock=lambda: now[0], sleep=sleep, timeout=2)
    assert now[0] == 2
