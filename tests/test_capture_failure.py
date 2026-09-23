"""Capture-failure reporting in record_device: a dead stream must call
on_failure so the tray can warn the user, instead of silently producing
a half-recorded meeting (the Sep 2026 display-audio loopback incidents)."""

import threading

from recorder import record_device

DEVICE = {
    "name": "Test Speakers [Loopback]",
    "defaultSampleRate": 44100.0,
    "maxInputChannels": 2,
    "index": 3,
}


class FailingOpenP:
    """PyAudio stand-in whose stream open fails outright."""

    def open(self, **kwargs):
        raise OSError(-9999, "Unanticipated host error")


class _FailingReadStream:
    def read(self, *args, **kwargs):
        raise OSError(-9999, "Unanticipated host error")

    def stop_stream(self):
        pass

    def close(self):
        pass


class FailingReadP:
    """PyAudio stand-in that opens fine but dies on the first read."""

    def open(self, **kwargs):
        return _FailingReadStream()


def test_open_failure_reports_device_name():
    failures = []
    frames = []
    record_device(FailingOpenP(), DEVICE, frames, threading.Event(),
                  on_failure=failures.append)
    assert failures == ["Test Speakers [Loopback]"]
    assert frames == []


def test_open_failure_without_callback_does_not_raise():
    record_device(FailingOpenP(), DEVICE, [], threading.Event())


def test_read_failure_reports_and_zeroes_level():
    failures = []
    levels = []
    record_device(FailingReadP(), DEVICE, [], threading.Event(),
                  level_callback=levels.append, on_failure=failures.append)
    assert failures == ["Test Speakers [Loopback]"]
    assert levels == [0.0]


class _FailDuringStopStream:
    """Read that raises only after stop was requested (teardown window)."""

    def __init__(self, stop_event):
        self._stop = stop_event

    def read(self, *args, **kwargs):
        self._stop.set()
        raise OSError(-9999, "Unanticipated host error")

    def stop_stream(self):
        pass

    def close(self):
        pass


def test_failure_during_stop_is_not_reported():
    stop = threading.Event()

    class P:
        def open(self, **kwargs):
            return _FailDuringStopStream(stop)

    failures = []
    record_device(P(), DEVICE, [], stop, on_failure=failures.append)
    assert failures == []
