import json
import sys
from types import SimpleNamespace

import pytest
from test_prepared_farm_check import Api as FarmApi
from test_prepared_route_check import AREA, ready

from maplebot import public_map
from tools import navigation_check, prepared_farm_check, prepared_route_check


@pytest.mark.parametrize('scores', [(-.001, -.001), (0, 0), (0, 1e-7), (1, 1.2)])
def test_map_ties_refuse_even_with_roundoff(monkeypatch, scores):
    monkeypatch.setattr(public_map, 'picture', lambda value: value)
    monkeypatch.setattr(public_map, 'match_score', lambda captured, index: scores[index])
    with pytest.raises(ValueError, match='Several maps'):
        public_map.identify(None, {1: {'miniMap': 0}, 2: {'miniMap': 1}})


def test_map_nonfinite_candidates_cannot_win(monkeypatch):
    monkeypatch.setattr(public_map, 'picture', lambda value: value)
    monkeypatch.setattr(public_map, 'match_score', lambda captured, value: value)
    assert public_map.identify(None, {1: {'miniMap': float('nan')}, 2: {'miniMap': 2}}) == 2
    with pytest.raises(ValueError, match='No candidate'):
        public_map.identify(None, {1: {'miniMap': float('inf')}})


def test_navigation_connection_loss_still_persists_partial_result(tmp_path, monkeypatch):
    monkeypatch.setattr(navigation_check, 'readiness', lambda status: None)
    status = {'navigation': {'map': {'proven_edges': 7}}}
    class Api:
        def status(self):
            if hasattr(self, 'read'):
                raise OSError('status lost')
            self.read = True
            return status

        def command(self, name, payload=None):
            if name == 'stop':
                raise OSError('stop lost')
    result = navigation_check.run(Api(), tmp_path / 'result', limit=1, chosen=['floor'])
    saved = json.loads((tmp_path / 'result/result.json').read_text())
    assert result == saved
    assert result['failure'] == 'status lost'
    assert result['status_error'] == 'status lost'
    assert result['stop_error'] == 'stop lost'
    assert result['proven_after'] == 7 and not result['after_is_current']


@pytest.mark.parametrize('farm', [True, False])
def test_prepared_failure_alarms_and_saves_when_cleanup_loses_connection(
        tmp_path, monkeypatch, farm):
    module = prepared_farm_check if farm else prepared_route_check
    initial = FarmApi('fh308').status() if farm else ready()
    class Api:
        def status(self):
            if getattr(self, 'lost', False):
                raise OSError('status lost')
            return initial

        def command(self, name, payload=None):
            raise OSError('stop lost')
    api = Api()
    def run(*args, **kwargs):
        api.lost = True
        raise RuntimeError('execution failed')
    alarms = []
    monkeypatch.setitem(sys.modules, 'winsound', SimpleNamespace(
        SND_FILENAME=0, PlaySound=lambda *args: alarms.append(args)))
    monkeypatch.setattr(module, '__file__', str(tmp_path / 'tools/check.py'))
    monkeypatch.setattr(module, 'settle', lambda api, status, *args: (status, True))
    monkeypatch.setattr(module, 'run', run)
    if farm:
        code = module.main(['--run', '--area', 'tree', '--origin', 'fh308'], api=api)
    else:
        monkeypatch.setattr(module, 'Debugger', lambda: api)
        code = module.main(['--run', '--area', AREA, '--origin', 'fh315', '--target', 'fh308'])
    assert code == 1 and len(alarms) == 1
    saved = json.loads(next(tmp_path.rglob('result.json')).read_text())
    assert saved['status_error'] == 'status lost' and saved['stop_error'] == 'stop lost'
    assert saved.get('error', saved.get('failure')) == 'execution failed'
    assert not saved['after_is_current']
