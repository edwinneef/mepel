"""Shared image-only structure candidates. No map IDs, templates or input authority."""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Structure:
    kind: str
    coordinate: float
    start: float
    end: float
    uncertainty: float


def distinct(values, gap=6):
    kept = []
    for value in sorted(values):
        if not kept or value - kept[-1] > gap:
            kept.append(value)
    return kept


def rung_axes(gray, edges):
    gx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0))
    gy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    vertical = (gx > 100) & (gx > gy * 1.5) & (edges > 0)
    horizontal = (gy > 100) & (gy > gx * 1.2) & (edges > 0)
    candidates = []
    for top in range(0, gray.shape[0] - 127, 48):
        scores = vertical[top:top + 128].sum(axis=0)
        peaks = []
        for x in np.argsort(-scores):
            if scores[x] < 24 or len(peaks) >= 48:
                break
            if all(abs(int(x) - old) >= 4 for old in peaks):
                peaks.append(int(x))
        for i, a in enumerate(sorted(peaks)):
            for b in sorted(peaks)[i + 1:]:
                if not 20 <= b - a <= 70:
                    continue
                strength = horizontal[top:top + 128, a + 3:b - 2].sum(axis=1)
                ys = distinct(np.flatnonzero(strength >= max(4, (b - a - 5) * .18)))
                if (len(ys) >= 5 and ys[-1] - ys[0] >= 70
                        and np.mean((np.diff(ys) >= 6) & (np.diff(ys) <= 28)) >= .8):
                    candidates.append(((a + b) / 2, top + ys[0], top + ys[-1],
                                       min(scores[a], scores[b])))
    result = []
    for axis, top, bottom, _ in sorted(candidates, key=lambda r: -r[3]):
        if not any(abs(axis - old.coordinate) < 10 for old in result):
            result.append(Structure("ladder", axis, float(top), float(bottom), 3))
    return result


def detect(image, actors=()):
    """Ladder rungs/rails, thin vertical pairs and horizontal surface candidates.

    Surface candidates deliberately retain artwork/collision uncertainty. Recognizing
    a straight edge does not identify a physical foothold or contact point.
    """
    if (image.ndim != 3 or image.shape[2] != 3 or image.shape[0] > 1200
            or image.shape[1] > 2048 or min(image.shape[:2]) < 80):
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 150)
    height, width = gray.shape
    allowed = np.full_like(gray, 255)
    allowed[:min(250, height), :min(400, width)] = 0
    allowed[max(0, height - 145):] = 0
    allowed[:min(180, height), max(0, width - 260):] = 0
    for box in actors:
        x, y, w, h = (int(box[k]) for k in ("x", "y", "width", "height"))
        allowed[max(0, y - 8):min(height, y + h + 8),
                max(0, x - 8):min(width, x + w + 8)] = 0
    edges &= allowed
    blue = cv2.inRange(cv2.cvtColor(image, cv2.COLOR_BGR2HSV),
                       (85, 70, 160), (130, 255, 255)) & allowed
    contours, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    portals = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if 20 <= w <= 100 and 50 <= h <= 200 and h >= w * 1.4:
            portals.append(Structure("portal", x + w / 2, y, y + h, 12))
    found = cv2.HoughLinesP(edges, 1, np.pi / 180, 18,
                            minLineLength=14, maxLineGap=3)
    if found is None:
        return portals[:8]
    lines = sorted((tuple(map(int, row[0])) for row in found),
                   key=lambda r: -max(abs(r[2] - r[0]), abs(r[3] - r[1])))[:2000]
    horizontal, vertical, rungs = [], [], []
    for x1, y1, x2, y2 in lines:
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dy <= 2:
            segment = (min(x1, x2), max(x1, x2), (y1 + y2) / 2)
            if dx >= 96:
                horizontal.append(segment)
            elif 14 <= dx <= 70:
                rungs.append(segment)
        if dx <= 2 and dy >= 70:
            vertical.append(((x1 + x2) / 2, min(y1, y2), max(y1, y2)))
    groups = []
    for left, right, y in sorted(rungs):
        center, span = (left + right) / 2, right - left
        group = next((g for g in groups if abs(center - g[0]) <= 4
                      and abs(span - g[1]) <= 10), None)
        if group is None:
            groups.append([center, span, [y]])
        else:
            group[2].append(y)
    ladders = rung_axes(gray, edges)
    for center, span, ys in groups:
        ys = distinct(ys)
        if len(ys) < 5 or ys[-1] - ys[0] < 50:
            continue
        gaps = np.diff(ys)
        spacing = float(np.median(gaps))
        if not 6 <= spacing <= 28 or np.mean(np.abs(gaps - spacing) <= 3) < .7:
            continue
        left, right = max(0, int(center - span)), min(width, int(center + span))
        rails = edges[int(ys[0]):int(ys[-1]) + 1, left:right].sum(axis=0)
        middle = int(center) - left
        if middle < 1 or middle >= len(rails) - 1:
            continue
        a, b = int(np.argmax(rails[:middle])), middle + int(np.argmax(rails[middle:]))
        minimum = (ys[-1] - ys[0]) * 255 * .2
        if b - a < span * .4 or min(rails[a], rails[b]) < minimum:
            continue
        axis = left + (a + b) / 2
        if not any(abs(axis - old.coordinate) < 10 for old in ladders):
            ladders.append(Structure("ladder", axis, ys[0], ys[-1], 3))
    ropes = []
    for i, (x, top, bottom) in enumerate(vertical[:256]):
        for other, upper, lower in vertical[i + 1:256]:
            overlap = min(bottom, lower) - max(top, upper)
            axis = (x + other) / 2
            if (2 <= abs(x - other) <= 8 and overlap >= 70
                    and not any(abs(axis - item.coordinate) < 28 for item in ladders)
                    and not any(abs(axis - r.coordinate) < 8 for r in ropes)):
                ropes.append(Structure("rope", axis, max(top, upper), min(bottom, lower), 4))
    surfaces = []
    for left, right, y in sorted(horizontal, key=lambda r: -(r[1] - r[0])):
        if not any(abs(y - s.coordinate) <= 4 and min(right, s.end) > max(left, s.start)
                   for s in surfaces):
            surfaces.append(Structure("surface", y, left, right, 12))
    return ladders[:16] + ropes[:16] + surfaces[:24] + portals[:8]
