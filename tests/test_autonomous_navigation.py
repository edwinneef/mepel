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


def test_jump_confirmation_waits_for_agreeing_landing(monkeypatch):
    from tools import autonomous_navigation as runner
    def snapshot(mode, height, surface):
        return {'mode': mode, 'focused': True,
                'player': {'box': {'y': height, 'height': 64}},
                'position': {'kind': 'platform' if surface else 'unknown',
                             'surface_id': surface, 'stale': False}}
    states = iter([snapshot('capture', 300, 'floor'),
                   snapshot('probe_wait', 300, 'floor'),
                   snapshot('probe_confirm', 230, None),
                   snapshot('probe_confirm', 280, None),
                   snapshot('probe_confirm', 300, 'floor')])
    commands = []
    class Api:
        def status(self):
            return next(states)
        def command(self, name, payload=None):
            commands.append(name)
            return {'id': 1, 'generation': 2, 'path': 'clip'}
    monkeypatch.setattr(runner.time, 'sleep', lambda _: None)
    result = runner.jump_check(Api())
    assert result['passed'] and result['height_range'] == 70
    assert commands == ['probe', 'clip', 'confirm_probe', 'stop']
