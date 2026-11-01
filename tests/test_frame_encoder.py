import threading

import cv2
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


def test_parallel_encoding_keeps_exact_bytes_and_packet_pairing():
    rng = np.random.default_rng(19)
    raw = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    annotated = raw.copy()
    annotated[10:20] = 0
    item = FramePacket(1, "one", raw, annotated, {"frame": 1}, 1.0)
    received = []
    encoder = FrameEncoder(lambda *args: received.append(args))
    try:
        encoder.publish(item)
        assert encoder.flush_through(1, 2)["complete"]
    finally:
        encoder.close()
    assert not encoder.worker.is_alive()
    assert len(received) == 1
    assert received[0][0] is item
    assert received[0][1] == cv2.imencode(".png", raw)[1].tobytes()
    assert received[0][2] == cv2.imencode(".png", annotated)[1].tobytes()
