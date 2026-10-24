import time
from importlib.resources import files

from maplebot.alarm import AlarmManager


def test_alarm_manager_starts_and_acknowledges_without_speakers():
    class Backend:
        def __init__(self):
            self.played = []

        def play_loop(self, path):
            self.played.append(path)

        def stop(self):
            self.played.append(None)

        def beep(self):
            return None

    backend = Backend()
    alarm = AlarmManager(backend=backend)
    alarm.start("incident-1")
    assert alarm.active
    assert alarm.acknowledge()
    assert not alarm.active


def test_packaged_alarm_resource_is_available_to_the_audio_backend():
    class Backend:
        def __init__(self):
            self.path = None

        def play_loop(self, path):
            self.path = path

        def stop(self):
            return None

        def beep(self):
            raise AssertionError("WAV playback should not use fallback")

    backend = Backend()
    alarm = AlarmManager(backend=backend)
    assert files("maplebot").joinpath("static/alarm.wav").is_file()
    alarm.start("incident-2")
    assert backend.path is not None and backend.path.is_file()
    assert alarm.snapshot()["fallback"] is False
    alarm.acknowledge()


def test_failed_wave_playback_repeats_fallback_until_acknowledged():
    class Backend:
        def __init__(self):
            self.beeps = 0

        def play_loop(self, path):
            raise RuntimeError("no wave device")

        def stop(self):
            return None

        def beep(self):
            self.beeps += 1

    backend = Backend()
    alarm = AlarmManager(backend=backend)
    alarm.start("incident-3")
    deadline = time.monotonic() + 1
    while backend.beeps < 2:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert alarm.active
    alarm.acknowledge()
    beeps = backend.beeps
    time.sleep(0.3)
    assert backend.beeps == beeps
