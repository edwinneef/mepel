"""Opt-in candidate appearances. Never supplies templates to recognition or input."""

import base64
import hashlib
import json
import queue
import re
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np


class PoseCollection:
    def __init__(self, root: Path, *, limit: int = 32, interval: float = 3):
        self.root, self.limit, self.interval = root, limit, interval
        self.lock = threading.RLock()
        self.enabled = False
        self.identity = self.outfit = ""
        self.reason = "Off"
        self.saved = self.duplicates = self.rejected = 0
        self.previous = None
        self.last_sample = float("-inf")
        self.examples = []
        self.jobs = queue.Queue(maxsize=2)
        self.closed = threading.Event()
        self.writer = None
        self.deadline = 0.0
        self.candidates = []
        self.rejection_reasons = {}
        self.last_rejection = ""

    def configure(self, identity: str = "", outfit: str = "") -> dict:
        with self.lock:
            self.enabled = False
            self.previous = None
            if not identity:
                self.reason = "Off"
                return self.snapshot()
            if self.closed.is_set() or self.jobs.unfinished_tasks:
                raise ValueError("Wait for pending pose writes before changing collection")
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", identity + "") or not re.fullmatch(
                r"[a-zA-Z0-9_-]{1,64}", outfit
            ):
                raise ValueError("Identity/outfit must use letters, digits, _ or -")
            directory = self.root / identity / outfit
            examples = []
            candidates = []
            files = list(directory.glob("*.json"))
            if len(files) > self.limit:
                raise ValueError("Collection exceeds its limit; existing files preserved")
            for path in files:
                data = json.loads(path.read_text())
                if data["identity"] != identity or data["outfit"] != outfit:
                    raise ValueError("Pose identity mismatch")
                crop = cv2.imdecode(np.frombuffer(base64.b64decode(data["crop"]), np.uint8), 1)
                if crop is None:
                    raise ValueError("Unreadable saved pose")
                digest = hashlib.sha256(crop.tobytes()).hexdigest()
                if data.get("crop_sha256") != digest:
                    raise ValueError("Saved pose checksum mismatch")
                candidates.append(dict(id=path.stem, crop=data["crop"]))
                examples.append((crop, data["anchor"], data["mask"], digest))
            self.identity, self.outfit = identity, outfit
            self.examples, self.saved = examples, len(examples)
            self.candidates = candidates
            self.duplicates = self.rejected = 0
            self.rejection_reasons = {}
            self.last_rejection = ""
            self.last_sample = float("-inf")
            self.deadline = time.monotonic() + 30
            self.enabled = self.saved < self.limit
            self.reason = "Waiting for two clear name observations" if self.enabled else "Full"
            return self.snapshot()

    def snapshot(self) -> dict:
        with self.lock:
            if self.enabled and time.monotonic() >= self.deadline:
                self.enabled, self.reason = False, "Capture complete"
            return dict(enabled=self.enabled, identity=self.identity, outfit=self.outfit,
                        saved=self.saved, duplicates=self.duplicates, rejected=self.rejected,
                        pending=self.jobs.unfinished_tasks, limit=self.limit, reason=self.reason,
                        candidates=list(self.candidates), last_rejection=self.last_rejection,
                        rejection_reasons=dict(self.rejection_reasons))

    def reject(self, reason: str) -> None:
        with self.lock:
            self.previous = None
            self.rejected += 1
            self.last_rejection = reason
            self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1
            self.reason = reason

    def observe(self, image, detector, observation, now: float, captured_at: float,
                generation, *, eligible: bool) -> None:
        with self.lock:
            if not self.snapshot()["enabled"]:
                return
            if not eligible or not 0 <= time.time() - captured_at <= .5:
                self.reject("Waiting for a fresh verified frame")
                return
            player = observation.player
            if not player or player.tracked or any(
                failure not in {"Player sprite not matched; located by name tag",
                                "No visible monster template matches"}
                for failure in observation.failures
            ):
                # Fail closed, including unknown/ambiguous nearby player evidence.
                self.reject("Waiting for unambiguous player evidence")
                return
            if now - self.last_sample < self.interval:
                return
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            matches = [(tag, match) for tag in detector.nametags
                       for match in detector.nametag_matches(gray, tag, .95)]
            selected = [(tag, match) for tag, match in matches if tag.name == self.identity]
            if len(selected) != 1:
                self.reject("Name missing or ambiguous")
                return
            tag, match = selected[0]
            body = detector.body_from_nametag(tag, match.box)
            if body.iou(player.box) < .5:
                self.reject("Name and player disagree")
                return
            if any(body.iou(monster.box) > 0 for monster in observation.monsters) or any(
                other.name != self.identity and
                not (found.box == match.box and np.array_equal(other.text, tag.text)) and
                abs(found.box.center[0] - match.box.center[0]) < 120 and
                abs(found.box.center[1] - match.box.center[1]) < 120
                for other, found in matches
            ):
                self.reject("Nearby appearance overlaps collection")
                return
            previous = self.previous
            self.previous = (generation, now, body)
            if (previous is None or previous[0] != generation or
                    not 0 < now - previous[1] <= .5 or previous[2].iou(body) < .5):
                self.reason = "Waiting for second agreeing observation"
                return
            if (body.x < 0 or body.y < 0 or body.x + body.width > image.shape[1] or
                    body.feet > image.shape[0] or max(body.width, body.height) > 256):
                self.reject("Invalid or clipped crop")
                return
            crop = image[body.y:body.feet, body.x:body.x + body.width].copy()
            anchor, mask = detector._player_anchor(crop)
            if anchor is None or mask is None:
                self.reject("No clean sprite mask")
                return
            self.last_sample = now
            self.previous = None
            metadata = dict(captured_at=captured_at, capture_clock=now, generation=generation,
                            source_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                            name_score=match.confidence, name_box=asdict(match.box),
                            sprite_box=asdict(body), provenance="two-full-name-observations")
            self.submit(crop, mask, asdict(anchor), metadata)

    def submit(self, crop, mask, anchor: dict, metadata: dict) -> None:
        with self.lock:
            if not self.enabled or self.closed.is_set():
                return
            mask_png = base64.b64encode(cv2.imencode(".png", mask)[1]).decode()
            digest = hashlib.sha256(crop.tobytes()).hexdigest()
            for existing, old_anchor, old_mask, old_digest in self.examples:
                if existing.shape == crop.shape and old_anchor == anchor and old_mask == mask_png:
                    difference = cv2.absdiff(existing, crop)
                    if digest == old_digest or (difference.max() <= 8 and difference.mean() <= 1):
                        self.duplicates += 1
                        self.reason = "Duplicate skipped"
                        return
            if len(self.examples) >= self.limit:
                self.enabled, self.reason = False, "Full"
                return
            data = dict(metadata, identity=self.identity, outfit=self.outfit, anchor=anchor,
                        mask=mask_png, crop_sha256=digest, candidate_only=True,
                        crop=base64.b64encode(cv2.imencode(".png", crop)[1]).decode())
            path = self.root / self.identity / self.outfit / (uuid.uuid4().hex + ".json")
            try:
                self.jobs.put_nowait((path, data))
            except queue.Full:
                self.reject("Writer busy; sample skipped")
                return
            if self.writer is None:
                self.writer = threading.Thread(
                    target=self._write, daemon=True, name="pose-writer")
                self.writer.start()
            self.examples.append((crop.copy(), anchor, mask_png, digest))
            self.reason = "Saving candidate"
            if len(self.examples) >= self.limit:
                self.enabled, self.reason = False, "Full"

    def _write(self) -> None:
        while not self.closed.is_set() or not self.jobs.empty():
            try:
                path, data = self.jobs.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(data), encoding="utf-8")
                temporary.replace(path)
                with self.lock:
                    self.saved += 1
                    self.candidates.append(dict(id=path.stem, crop=data["crop"]))
            except Exception as error:
                with self.lock:
                    self.enabled, self.reason = False, f"Pose write failed: {error}"
            finally:
                self.jobs.task_done()

    def close(self) -> None:
        self.configure()
        self.closed.set()
        if self.writer is not None:
            self.writer.join(timeout=1)
        if self.writer is not None and self.writer.is_alive():
            self.reason = "Shutdown with pose writes still pending"
