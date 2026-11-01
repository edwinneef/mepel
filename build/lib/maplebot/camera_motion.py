"""Conservative image-only camera translation when global correlation is ambiguous."""

import cv2
import numpy as np


def feature_translation(previous: np.ndarray, current: np.ndarray,
                        hint: tuple | None = None) -> tuple[tuple, float]:
    if previous.shape != current.shape or min(current.shape) < 40:
        return (0, 0), 0
    h, w = current.shape
    mask = np.full_like(previous, 255)
    # Fixed game HUD pixels are not evidence of world motion.
    mask[h - min(140, h // 5):] = 0
    mask[:min(200, h // 3), :min(240, w // 4)] = 0
    mask[:min(180, h // 3), w - min(220, w // 4):] = 0
    points = cv2.goodFeaturesToTrack(previous, 200, .02, 12, mask=mask)
    if points is None or len(points) < 24:
        return (0, 0), 0
    # At ~3 fps, scrolling can move farther than an unseeded local search finds.
    # Correlation supplies a search hint only; all acceptance comes from verified
    # forward/backward feature agreement below.
    seeded = (hint is not None and np.isfinite(hint).all()
              and abs(hint[0]) <= w * .2 and abs(hint[1]) <= h * .2)
    initial = points + np.float32(hint).reshape(1, 1, 2) if seeded else None
    forward, ok, error = cv2.calcOpticalFlowPyrLK(
        previous, current, points, initial, winSize=(21, 21), maxLevel=4,
        flags=cv2.OPTFLOW_USE_INITIAL_FLOW if seeded else 0)
    if forward is None:
        return (0, 0), 0
    backward, reverse_ok, _ = cv2.calcOpticalFlowPyrLK(
        current, previous, forward, points.copy(), winSize=(21, 21), maxLevel=4,
        flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
    if backward is None:
        return (0, 0), 0
    keep = ((ok[:, 0] > 0) & (reverse_ok[:, 0] > 0)
            & (error[:, 0] < 20)
            & (np.linalg.norm(backward[:, 0] - points[:, 0], axis=1) < 1))
    starts = points[:, 0][keep]
    delta = forward[:, 0][keep] - starts
    if len(delta) < 24 or not np.isfinite(delta).all():
        return (0, 0), 0
    # A translation must dominate independently tracked features, not one actor.
    distances = np.linalg.norm(delta[:, None] - delta[None, :], axis=2)
    inliers = distances[np.argmax((distances <= 2).sum(axis=1))] <= 2
    confidence = float(inliers.mean())
    spread = np.ptp(starts[inliers], axis=0)
    if (inliers.sum() < 24 or confidence < .60 or spread[0] < w * .25
            or spread[1] < h * .20):
        return (0, 0), 0
    dx, dy = np.median(delta[inliers], axis=0)
    if abs(dx) > w * .2 or abs(dy) > h * .2:
        return (0, 0), 0
    return (float(dx), float(dy)), confidence
