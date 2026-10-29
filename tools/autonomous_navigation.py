"""Resumable native validation; the agent diagnoses failures before --fix-revision changes."""
import argparse
import ctypes
import json
import time
from ctypes import wintypes
from pathlib import Path
from urllib.request import Request, urlopen

from maplebot.navigation import RouteMap
from tools.navigation_check import Debugger, run, targets


def bounded_destination(status, target):
    """Split long journeys at a platform; each engine route retains its own limits."""
    p = status['position']
    profile = Path(__file__).resolve().parents[1] / 'data' / 'areas' / (p['area_id'] + '.json')
    graph = RouteMap.computed(json.loads(profile.read_text()))
    try:
        graph.plan(p['surface_id'], target, origin_feet=p['feet'])
        return target
    except ValueError:
        candidates = []
        for node in targets(status):
            if node == target:
                continue
            try:
                first = graph.plan(p['surface_id'], node, origin_feet=p['feet'])
                rest = graph.plan(node, target)
                candidates.append((len(rest.edges), len(first.edges), node))
            except ValueError:
                continue
        if not candidates:
            raise RuntimeError('No bounded intermediate platform route available') from None
        return min(candidates)[2]


def idle_seconds():
    class LastInput(ctypes.Structure):
        _fields_ = [("size", wintypes.UINT), ("tick", wintypes.DWORD)]
    info = LastInput()
    info.size = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise RuntimeError("Cannot verify user idle time")
    return ((ctypes.windll.kernel32.GetTickCount() - info.tick) & 0xffffffff) / 1000


def wait_idle(idle=idle_seconds, clock=time.monotonic, sleep=time.sleep, timeout=None,
              cancelled=lambda: False):
    # User activity is a pause, not a failed gameplay test requiring a new revision.
    deadline = clock() + timeout if timeout is not None else None
    while True:
        if cancelled():
            raise RuntimeError('Operator state changed; pending focus handoff canceled')
        if idle() >= 10:
            return
        if deadline is not None and clock() >= deadline:
            raise RuntimeError("User remains active; validation paused without taking focus")
        sleep(.25)


def post(api, route):
    request = Request(api.base + '/api/' + route, data=b'{}',
                      headers={'X-Debug-Token': api.token, 'Content-Type': 'application/json'})
    with urlopen(request, timeout=3) as response:
        return json.load(response)


def prepare(api, area, reviewed_incident=None):
    def handoff():
        epoch = api.status()['command_epoch']
        wait_idle(cancelled=lambda: api.status()['command_epoch'] != epoch)
    handoff()
    if api.status()['mode'] != 'capture':
        raise RuntimeError('Bot must be Off before autonomous validation')
    post(api, 'overlay_close')
    time.sleep(1)
    api.command('position_start', {'area_id': area})
    handoff()
    if not api.command('focus_game', {'click_fallback': True}).get('focused'):
        raise RuntimeError('Game focus request failed')
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        s = api.status()
        p = s.get('position') or {}
        if p.get('area_id') != area:
            raise RuntimeError('Unexpected tracked map')
        if s.get('focused') and s.get('player') and p.get('surface_id'):
            alarm = s.get('alarm') or {}
            if alarm.get('active'):
                if alarm.get('incident_id') != reviewed_incident:
                    raise RuntimeError('Unreviewed alarm; inspect its clip before acknowledgement')
                api.command('acknowledge', {'incident_id': reviewed_incident})
            return s
        time.sleep(.25)
    raise RuntimeError('Focus, recognized player and stable origin not confirmed')


def jump_check(api):
    before = api.status()
    origin = before['position']['surface_id']
    if before['position']['kind'] != 'platform':
        raise RuntimeError('Jump validation needs a platform')
    probe = api.command('probe', {'action': 'jump'})
    samples = []
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            time.sleep(.1)
            s = api.status()
            samples.append(s)
            if not s.get('focused'):
                raise RuntimeError('Focus lost during jump probe')
            if s['mode'] == 'capture':
                raise RuntimeError('Jump probe stopped before confirmation')
            heights = [v['player']['box']['y'] + v['player']['box']['height']
                       for v in samples if v.get('player')]
            position = s.get('position') or {}
            if (s['mode'] == 'probe_confirm' and heights
                    and max(heights) - min(heights) >= 12
                    and position.get('surface_id') == origin
                    and not position.get('stale')):
                break
        heights = [s['player']['box']['y'] + s['player']['box']['height']
                   for s in samples if s.get('player')]
        settled = samples[-1].get('position') or {}
        passed = (heights and max(heights)-min(heights) >= 12
                  and settled.get('surface_id') == origin and not settled.get('stale'))
        clip = api.command('clip')['path']
        result = api.command('confirm_probe' if passed else 'reject_probe',
                             {'id': probe['id'], 'generation': probe['generation']})
        return {'passed': bool(passed), 'clip': clip, 'result': result,
                'height_range': max(heights)-min(heights) if heights else None}
    except Exception as error:
        return {'passed': False, 'error': str(error), 'clip': api.command('clip')['path'],
                'stop': api.status().get('stop')}
    finally:
        api.command('stop')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--area', required=True)
    parser.add_argument('--floor', required=True)
    parser.add_argument('--fix-revision', required=True)
    parser.add_argument('--reviewed-incident')
    args = parser.parse_args()
    state = json.loads(args.state.read_text()) if args.state.exists() else {
        'area': args.area, 'completed': [], 'runs': [], 'jump': None}
    if state['area'] != args.area:
        raise RuntimeError('State belongs to another map')
    if state.get('failure') and state.get('revision') == args.fix_revision:
        raise RuntimeError('Unchanged failed revision; inspect evidence and fix before resuming')
    api = Debugger()
    state.update(revision=args.fix_revision, failure=None)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.state.write_text(json.dumps(state, indent=2))
    try:
        s = prepare(api, args.area, args.reviewed_incident)
        if s['position']['kind'] == 'rope':
            output = args.state.parent / ('recovery-' + str(time.time_ns()))
            result = run(api, output, limit=1, chosen=[args.floor])
            state['runs'].append(str(output / 'result.json'))
            save()
            if result['failure']:
                raise RuntimeError(result['failure'])
            state['recovered'] = True
        if not (state.get('jump') or {}).get('passed'):
            prepare(api, args.area, args.reviewed_incident)
            state['jump'] = jump_check(api)
            state.setdefault('jump_attempts', []).append(state['jump'])
            save()
            if not state['jump']['passed']:
                raise RuntimeError('Jump effect not verified; inspect probe clip')
        s = prepare(api, args.area, args.reviewed_incident)
        state.setdefault('targets', targets(s)[:6])
        queue = list(state['targets'])
        intermediate_count = 0
        while queue:
            target = queue.pop(0)
            if target in state['completed']:
                continue
            s = prepare(api, args.area, args.reviewed_incident)
            if s['position']['surface_id'] == target:
                raise RuntimeError('Target already occupied without recorded arrival')
            output = args.state.parent / ('route-' + str(time.time_ns()))
            destination = bounded_destination(s, target)
            result = run(api, output, limit=1, chosen=[destination])
            state['runs'].append(str(output / 'result.json'))
            if result['failure']:
                raise RuntimeError(result['failure'])
            if destination == target:
                state['completed'].append(target)
                intermediate_count = 0
            else:
                intermediate_count += 1
                if intermediate_count >= 3:
                    raise RuntimeError('Intermediate route budget exhausted')
                queue.insert(0, target)
            save()
        state['passed'] = True
    except Exception as error:
        state['failure'] = str(error)
        raise
    finally:
        try:
            api.command('stop')
        finally:
            save()
            print(json.dumps(state), flush=True)


if __name__ == '__main__':
    main()
