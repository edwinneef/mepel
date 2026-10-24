import threading

import numpy as np

from maplebot.frame_encoder import FrameEncoder, FramePacket


def packet(sequence):
    frame = np.full((8, 8, 3), sequence, dtype=np.uint8)
    return FramePacket(sequence, f"{sequence:08d}", frame, frame.copy(), {}, float(sequence))


def test_encoder_replaces_one_unstarted_packet_and_flushes_the_newest_frame():
    started = threading.Event()
    release = threading.Event()
    encoded = []

    def on_encoded(item, raw, annotated, elapsed):
        encoded.append(item.sequence)
        if item.sequence == 0:
            started.set()
            assert release.wait(1)

    encoder = FrameEncoder(on_encoded)
    try:
        encoder.publish(packet(0))
        assert started.wait(1)
        encoder.publish(packet(1))
        encoder.publish(packet(2))
        assert encoder.snapshot()["queue_depth"] == 1
        release.set()
        result = encoder.flush_through(2, 2)
        assert result["complete"] is True
        assert result["replaced"] == 1
        assert encoded == [0, 2]
        assert encoder.snapshot()["queue_depth"] == 0
    finally:
        encoder.close()


def test_encoder_reports_a_worker_failure_to_bounded_flush():
    encoder = FrameEncoder(lambda *args: None)
    try:
        bad = FramePacket(0, "bad", None, None, {}, 0.0)
        encoder.publish(bad)
        result = encoder.flush_through(0, 2)
        assert result["complete"] is False
        assert result["reason"] == "failure"
        assert result["failure"]
    finally:
        encoder.close()
